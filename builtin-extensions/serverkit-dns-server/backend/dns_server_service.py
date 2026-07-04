"""Authoritative DNS hosting service (serverkit-dns-server extension).

Runs PowerDNS Authoritative Server (SQLite backend) in a managed Docker
container so a ServerKit box can BE the nameserver for its domains. Built
for homelab / air-gapped setups; it complements the provider-based DNS
integrations (Cloudflare etc.) and never replaces them.

Design notes, mirroring the serverkit-crowdsec extension:

* **Two choke-points** — every Docker invocation goes through
  :meth:`_docker` (privilege escalation, timeouts, error shaping) and every
  PowerDNS HTTP API call goes through :meth:`_api` (auth header, JSON,
  error shaping). Nothing else shells out or talks HTTP.
* **Authoritative only** — ``pdns-auth`` does not recurse, by design. This
  extension will never answer recursive queries for clients; it only serves
  the zones the operator creates. Point resolvers elsewhere.
* **Best-effort, Linux-only** — on Windows (dev) or when Docker is absent,
  calls return a clean error dict instead of raising.
* **State lives in PowerDNS** — zone data is PowerDNS's own SQLite file
  under ``/var/serverkit/dns-server``; the extension's few settings
  (generated API key, NS hostname, hostmaster email) live in the plugin
  config store (``plugins_sdk.config``). No core models, no migrations.
"""
import json
import logging
import os
import re
import secrets
import socket
import struct
import subprocess

import requests

from app.utils.system import run_privileged, is_command_available

logger = logging.getLogger(__name__)

SLUG = 'serverkit-dns-server'

# Official PowerDNS Authoritative Server image, 4.9.x line.
IMAGE = 'powerdns/pdns-auth-49'
CONTAINER_NAME = 'serverkit-dns-server'
DATA_DIR = '/var/serverkit/dns-server'
# SQLite path *inside* the container (DATA_DIR is bind-mounted there).
CONTAINER_DB_DIR = '/var/lib/powerdns'

API_HOST = '127.0.0.1'
API_PORT = 8081
API_BASE = f'http://{API_HOST}:{API_PORT}/api/v1'
API_TIMEOUT = 10
DOCKER_TIMEOUT = 120

DOCS_URL = 'https://doc.powerdns.com/authoritative/'

# Record types the panel will read/write. Anything else is rejected.
ALLOWED_RECORD_TYPES = frozenset(
    ('A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SRV', 'CAA', 'PTR', 'SOA'))

# Hostname labels: letters/digits/hyphen, plus '_' (SRV/TXT conventions) and a
# lone '*' for wildcards. No leading/trailing hyphen.
_LABEL_RE = re.compile(r'^(?:\*|_?[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)$')
_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}\.?$)[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?'
    r'(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)+\.?$')
_EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

# Public resolvers asked during the best-effort delegation check.
DELEGATION_RESOLVERS = ('1.1.1.1', '8.8.8.8')
_QTYPE_NS = 2
_QCLASS_IN = 1


def _canonical_zone(zone):
    """Normalize a zone name to lowercase, dot-terminated. None if invalid."""
    if not zone or not isinstance(zone, str):
        return None
    z = zone.strip().lower().rstrip('.')
    if not z or not _HOSTNAME_RE.match(z + '.') or '*' in z:
        return None
    return z + '.'


def _valid_record_name(name):
    """True when every label of *name* (dot-terminated FQDN) is well-formed."""
    labels = name.rstrip('.').split('.')
    return all(_LABEL_RE.match(lbl) for lbl in labels)


class DnsServerService:
    """Stateless wrapper around Docker + the PowerDNS HTTP API."""

    # ---------- config (plugin config store) ----------

    @classmethod
    def _config(cls):
        """Saved extension settings from the plugin config store."""
        from app.plugins_sdk import config as plugin_config
        return plugin_config(SLUG)

    @classmethod
    def _save_config(cls, updates):
        """Merge *updates* into the plugin's stored config.

        The SDK ``config()`` helper is read-only (the panel owns writes), so
        the generated API key is persisted through the InstalledPlugin row
        directly. Returns False when the plugin row is absent (dev shells).
        """
        from app import db
        from app.models.plugin import InstalledPlugin
        row = InstalledPlugin.query.filter_by(slug=SLUG).first()
        if not row:
            logger.warning('%s: no InstalledPlugin row; config not persisted', SLUG)
            return False
        merged = dict(row.config or {})
        merged.update(updates)
        row.config = merged
        db.session.commit()
        return True

    # ---------- docker choke-point ----------

    @classmethod
    def _docker(cls, args, timeout=DOCKER_TIMEOUT):
        """Run ``docker <args>`` and return a normalized result dict."""
        if os.name == 'nt':
            return {'success': False,
                    'error': 'The DNS server extension is not supported on Windows.'}
        if not is_command_available('docker'):
            return {'success': False, 'not_installed': True,
                    'error': 'Docker is not installed on this host.'}
        cmd = ['docker'] + list(args)
        try:
            result = run_privileged(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': f'docker timed out after {timeout}s'}
        except (OSError, subprocess.SubprocessError) as e:
            return {'success': False, 'error': f'Failed to run docker: {e}'}
        out = {
            'success': result.returncode == 0,
            'returncode': result.returncode,
            'stdout': result.stdout or '',
            'stderr': result.stderr or '',
        }
        if not out['success']:
            out['error'] = (out['stderr'] or out['stdout'] or 'docker failed').strip()
        return out

    # ---------- PowerDNS API choke-point ----------

    @classmethod
    def _api(cls, method, path, payload=None):
        """Call the container's PowerDNS HTTP API (loopback only).

        Returns ``{'success': True, 'data': <json-or-None>}`` or an error
        dict. The web server is published on 127.0.0.1 exclusively, so this
        never leaves the host.
        """
        api_key = cls._config().get('api_key')
        if not api_key:
            return {'success': False,
                    'error': 'PowerDNS API key is not configured. Reinstall the DNS server.'}
        try:
            resp = requests.request(
                method, API_BASE + path,
                headers={'X-API-Key': api_key},
                json=payload,
                timeout=API_TIMEOUT,
            )
        except requests.RequestException as e:
            return {'success': False,
                    'error': f'PowerDNS API is unreachable: {e}'}
        if resp.status_code >= 400:
            try:
                detail = resp.json().get('error') or resp.text
            except ValueError:
                detail = resp.text
            return {'success': False,
                    'error': f'PowerDNS API error ({resp.status_code}): {detail}'.strip()}
        if not resp.content:
            return {'success': True, 'data': None}
        try:
            return {'success': True, 'data': resp.json()}
        except ValueError:
            return {'success': False, 'error': 'PowerDNS API returned invalid JSON'}

    # ---------- container lifecycle ----------

    @classmethod
    def is_installed(cls):
        """True when the managed container exists (running or not)."""
        if os.name == 'nt':
            return False
        res = cls._docker(['inspect', '--format', '{{.State.Running}}',
                           CONTAINER_NAME], timeout=20)
        return bool(res.get('success'))

    @classmethod
    def get_status(cls):
        """Installed / running / version / config summary, best-effort."""
        status = {
            'installed': False,
            'running': False,
            'version': None,
            'image': IMAGE,
            'container': CONTAINER_NAME,
            'ns_hostname': cls._config().get('ns_hostname') if os.name != 'nt' else None,
            'authoritative_only': True,
            'docs_url': DOCS_URL,
        }
        if os.name == 'nt':
            return status
        res = cls._docker(['inspect', '--format', '{{.State.Running}}',
                           CONTAINER_NAME], timeout=20)
        if not res.get('success'):
            return status
        status['installed'] = True
        status['running'] = res.get('stdout', '').strip() == 'true'
        if status['running']:
            info = cls._api('GET', '/servers/localhost')
            if info.get('success') and isinstance(info.get('data'), dict):
                status['version'] = info['data'].get('version')
        return status

    @classmethod
    def install(cls, ns_hostname, admin_email):
        """Create and start the PowerDNS container.

        * SQLite state bind-mounted at ``DATA_DIR`` (the official image
          bootstraps the schema on first start).
        * Port 53 published on tcp+udp (the box becomes a nameserver).
        * HTTP API enabled with a generated key, web server published on
          **127.0.0.1 only** — never reachable off-host.
        """
        if os.name == 'nt':
            return {'success': False,
                    'error': 'The DNS server extension is not supported on Windows.'}
        ns_hostname = (ns_hostname or '').strip().lower().rstrip('.')
        admin_email = (admin_email or '').strip()
        if not ns_hostname or not _HOSTNAME_RE.match(ns_hostname):
            return {'success': False,
                    'error': f'Invalid nameserver hostname: {ns_hostname!r}'}
        if not admin_email or not _EMAIL_RE.match(admin_email):
            return {'success': False,
                    'error': f'Invalid hostmaster email: {admin_email!r}'}
        if cls.is_installed():
            return {'success': False,
                    'error': 'The DNS server container already exists. Uninstall it first.'}

        dir_res = run_privileged(['mkdir', '-p', DATA_DIR])
        if getattr(dir_res, 'returncode', 1) != 0:
            return {'success': False,
                    'error': f'Could not create data directory {DATA_DIR}: '
                             f'{(dir_res.stderr or "").strip()}'}

        api_key = secrets.token_hex(24)
        run_args = [
            'run', '-d',
            '--name', CONTAINER_NAME,
            '--restart', 'unless-stopped',
            '-p', '53:53/udp',
            '-p', '53:53/tcp',
            '-p', f'{API_HOST}:{API_PORT}:{API_PORT}',
            '-v', f'{DATA_DIR}:{CONTAINER_DB_DIR}',
            IMAGE,
            # pdns_server flags (the image forwards container args to pdns):
            '--api=yes',
            f'--api-key={api_key}',
            '--webserver=yes',
            '--webserver-address=0.0.0.0',
            f'--webserver-port={API_PORT}',
            '--webserver-allow-from=0.0.0.0/0',
            '--launch=gsqlite3',
            f'--gsqlite3-database={CONTAINER_DB_DIR}/pdns.sqlite3',
            '--gsqlite3-dnssec=yes',
        ]
        res = cls._docker(run_args)
        if not res.get('success'):
            return {'success': False,
                    'error': res.get('error', 'Failed to start the PowerDNS container')}

        persisted = cls._save_config({
            'api_key': api_key,
            'ns_hostname': ns_hostname,
            'admin_email': admin_email,
        })
        result = {'success': True,
                  'message': 'PowerDNS authoritative server installed',
                  'container': CONTAINER_NAME}
        if not persisted:
            result['warning'] = ('Container started but the API key could not be '
                                 'persisted to the plugin config store.')
        return result

    @classmethod
    def uninstall(cls, keep_data=True):
        """Remove the container; optionally delete the SQLite zone data."""
        if os.name == 'nt':
            return {'success': False,
                    'error': 'The DNS server extension is not supported on Windows.'}
        res = cls._docker(['rm', '-f', CONTAINER_NAME])
        if not res.get('success'):
            return {'success': False,
                    'error': res.get('error', 'Failed to remove the PowerDNS container')}
        if not keep_data:
            rm = run_privileged(['rm', '-rf', DATA_DIR])
            if getattr(rm, 'returncode', 1) != 0:
                return {'success': True,
                        'warning': f'Container removed but zone data at {DATA_DIR} '
                                   f'could not be deleted: {(rm.stderr or "").strip()}'}
        cls._save_config({'api_key': None})
        return {'success': True,
                'message': 'DNS server removed'
                           + ('' if keep_data else ' (zone data deleted)')}

    # ---------- zones ----------

    @classmethod
    def list_zones(cls):
        res = cls._api('GET', '/servers/localhost/zones')
        if not res.get('success'):
            return res
        zones = [{
            'name': z.get('name'),
            'kind': z.get('kind'),
            'serial': z.get('serial'),
            'dnssec': bool(z.get('dnssec')),
        } for z in (res.get('data') or [])]
        return {'success': True, 'zones': zones}

    @classmethod
    def create_zone(cls, zone):
        """Create a Native zone with a bootstrap SOA + NS from install params."""
        canonical = _canonical_zone(zone)
        if not canonical:
            return {'success': False, 'error': f'Invalid zone name: {zone!r}'}
        cfg = cls._config()
        ns_hostname = (cfg.get('ns_hostname') or '').rstrip('.')
        admin_email = cfg.get('admin_email') or ''
        if not ns_hostname or not admin_email:
            return {'success': False,
                    'error': 'Nameserver hostname / hostmaster email are not '
                             'configured. Reinstall the DNS server.'}
        hostmaster = admin_email.replace('@', '.').rstrip('.') + '.'
        soa_content = f'{ns_hostname}. {hostmaster} 1 10800 3600 604800 3600'
        payload = {
            'name': canonical,
            'kind': 'Native',
            'rrsets': [
                {
                    'name': canonical, 'type': 'SOA', 'ttl': 3600,
                    'changetype': 'REPLACE',
                    'records': [{'content': soa_content, 'disabled': False}],
                },
                {
                    'name': canonical, 'type': 'NS', 'ttl': 3600,
                    'changetype': 'REPLACE',
                    'records': [{'content': f'{ns_hostname}.', 'disabled': False}],
                },
            ],
        }
        res = cls._api('POST', '/servers/localhost/zones', payload)
        if not res.get('success'):
            return res
        return {'success': True, 'zone': canonical,
                'message': f'Zone {canonical} created'}

    @classmethod
    def delete_zone(cls, zone):
        canonical = _canonical_zone(zone)
        if not canonical:
            return {'success': False, 'error': f'Invalid zone name: {zone!r}'}
        res = cls._api('DELETE', f'/servers/localhost/zones/{canonical}')
        if not res.get('success'):
            return res
        return {'success': True, 'message': f'Zone {canonical} deleted'}

    @classmethod
    def get_zone(cls, zone):
        """Zone detail: normalized rrsets + dnssec flag."""
        canonical = _canonical_zone(zone)
        if not canonical:
            return {'success': False, 'error': f'Invalid zone name: {zone!r}'}
        res = cls._api('GET', f'/servers/localhost/zones/{canonical}')
        if not res.get('success'):
            return res
        data = res.get('data') or {}
        rrsets = [{
            'name': r.get('name'),
            'type': r.get('type'),
            'ttl': r.get('ttl'),
            'records': [rec.get('content') for rec in (r.get('records') or [])
                        if not rec.get('disabled')],
        } for r in (data.get('rrsets') or [])]
        return {'success': True, 'zone': {
            'name': data.get('name'),
            'kind': data.get('kind'),
            'serial': data.get('serial'),
            'dnssec': bool(data.get('dnssec')),
            'rrsets': rrsets,
        }}

    # ---------- rrsets ----------

    @classmethod
    def _rrset_target(cls, zone, name, rtype):
        """Validate + canonicalize an rrset target. Returns (zone, fqdn) or error dict."""
        canonical = _canonical_zone(zone)
        if not canonical:
            return {'success': False, 'error': f'Invalid zone name: {zone!r}'}
        rtype = (rtype or '').strip().upper()
        if rtype not in ALLOWED_RECORD_TYPES:
            allowed = ', '.join(sorted(ALLOWED_RECORD_TYPES))
            return {'success': False,
                    'error': f'Unsupported record type {rtype!r}. Allowed: {allowed}'}
        raw = (name or '').strip().lower()
        if raw in ('', '@', canonical.rstrip('.')):
            fqdn = canonical
        elif raw.endswith('.'):
            fqdn = raw
        else:
            fqdn = f'{raw}.{canonical}'
        if not (fqdn == canonical or fqdn.endswith('.' + canonical)):
            return {'success': False,
                    'error': f'{name!r} is not inside zone {canonical}'}
        if not _valid_record_name(fqdn):
            return {'success': False, 'error': f'Invalid record name: {name!r}'}
        return canonical, fqdn, rtype

    @classmethod
    def upsert_rrset(cls, zone, name, rtype, ttl, records):
        target = cls._rrset_target(zone, name, rtype)
        if isinstance(target, dict):
            return target
        canonical, fqdn, rtype = target
        try:
            ttl = int(ttl)
        except (TypeError, ValueError):
            return {'success': False, 'error': f'Invalid TTL: {ttl!r}'}
        if not (1 <= ttl <= 604800):
            return {'success': False, 'error': 'TTL must be between 1 and 604800'}
        values = [str(r).strip() for r in (records or []) if str(r).strip()]
        if not values:
            return {'success': False, 'error': 'At least one record value is required'}
        payload = {'rrsets': [{
            'name': fqdn, 'type': rtype, 'ttl': ttl, 'changetype': 'REPLACE',
            'records': [{'content': v, 'disabled': False} for v in values],
        }]}
        res = cls._api('PATCH', f'/servers/localhost/zones/{canonical}', payload)
        if not res.get('success'):
            return res
        return {'success': True, 'message': f'{rtype} record set saved for {fqdn}'}

    @classmethod
    def delete_rrset(cls, zone, name, rtype):
        target = cls._rrset_target(zone, name, rtype)
        if isinstance(target, dict):
            return target
        canonical, fqdn, rtype = target
        if rtype == 'SOA':
            return {'success': False,
                    'error': 'The SOA record cannot be deleted (edit it instead).'}
        payload = {'rrsets': [{
            'name': fqdn, 'type': rtype, 'changetype': 'DELETE', 'records': [],
        }]}
        res = cls._api('PATCH', f'/servers/localhost/zones/{canonical}', payload)
        if not res.get('success'):
            return res
        return {'success': True, 'message': f'{rtype} record set deleted for {fqdn}'}

    # ---------- DNSSEC ----------

    @classmethod
    def get_ds_records(cls, zone):
        """DS records (paste at the registrar/parent) from active cryptokeys."""
        canonical = _canonical_zone(zone)
        if not canonical:
            return {'success': False, 'error': f'Invalid zone name: {zone!r}'}
        res = cls._api('GET', f'/servers/localhost/zones/{canonical}/cryptokeys')
        if not res.get('success'):
            return res
        ds = []
        for key in res.get('data') or []:
            if key.get('active'):
                ds.extend(key.get('ds') or [])
        return {'success': True, 'ds_records': ds}

    @classmethod
    def set_dnssec(cls, zone, enabled):
        """Enable/disable DNSSEC. PowerDNS generates the keys server-side;
        enabling returns the DS records for the parent zone."""
        canonical = _canonical_zone(zone)
        if not canonical:
            return {'success': False, 'error': f'Invalid zone name: {zone!r}'}
        payload = {'dnssec': bool(enabled)}
        if enabled:
            payload['api_rectify'] = True
        res = cls._api('PUT', f'/servers/localhost/zones/{canonical}', payload)
        if not res.get('success'):
            return res
        if not enabled:
            return {'success': True, 'dnssec': False,
                    'message': f'DNSSEC disabled for {canonical}. Remove the DS '
                               f'records at your registrar.'}
        ds = cls.get_ds_records(canonical)
        return {'success': True, 'dnssec': True,
                'ds_records': ds.get('ds_records', []) if ds.get('success') else [],
                'message': f'DNSSEC enabled for {canonical}. Publish the DS '
                           f'records at your registrar to complete the chain.'}

    # ---------- delegation check (minimal stdlib DNS client) ----------

    @staticmethod
    def _build_ns_query(zone, query_id):
        """Build a DNS query packet asking for the NS records of *zone*."""
        header = struct.pack('>HHHHHH', query_id, 0x0100, 1, 0, 0, 0)
        question = b''
        for label in zone.rstrip('.').split('.'):
            encoded = label.encode('idna') if not label.isascii() else label.encode()
            question += struct.pack('>B', len(encoded)) + encoded
        question += b'\x00' + struct.pack('>HH', _QTYPE_NS, _QCLASS_IN)
        return header + question

    @staticmethod
    def _parse_name(data, offset):
        """Decode a (possibly compressed) DNS name. Returns (name, next_offset)."""
        labels = []
        jumped = False
        next_offset = offset
        hops = 0
        while True:
            if offset >= len(data):
                raise ValueError('truncated DNS name')
            length = data[offset]
            if length & 0xC0 == 0xC0:  # compression pointer
                if offset + 1 >= len(data):
                    raise ValueError('truncated compression pointer')
                pointer = struct.unpack('>H', data[offset:offset + 2])[0] & 0x3FFF
                if not jumped:
                    next_offset = offset + 2
                    jumped = True
                offset = pointer
                hops += 1
                if hops > 32:
                    raise ValueError('compression loop')
                continue
            if length == 0:
                if not jumped:
                    next_offset = offset + 1
                break
            offset += 1
            labels.append(data[offset:offset + length].decode('ascii', 'replace'))
            offset += length
        return '.'.join(labels).lower(), next_offset

    @classmethod
    def _parse_ns_response(cls, data, query_id):
        """Extract NS names from a DNS response (answer + authority sections)."""
        if len(data) < 12:
            raise ValueError('truncated DNS header')
        rid, flags, qdcount, ancount, nscount, _ = struct.unpack('>HHHHHH', data[:12])
        if rid != query_id:
            raise ValueError('DNS response id mismatch')
        rcode = flags & 0x000F
        if rcode not in (0, 3):  # NOERROR or NXDOMAIN
            raise ValueError(f'DNS query failed with rcode {rcode}')
        offset = 12
        for _ in range(qdcount):
            _, offset = cls._parse_name(data, offset)
            offset += 4  # qtype + qclass
        ns_names = []
        for _ in range(ancount + nscount):
            _, offset = cls._parse_name(data, offset)
            if offset + 10 > len(data):
                raise ValueError('truncated resource record')
            rtype, _, _, rdlength = struct.unpack('>HHIH', data[offset:offset + 10])
            offset += 10
            if rtype == _QTYPE_NS:
                name, _ = cls._parse_name(data, offset)
                ns_names.append(name)
            offset += rdlength
        return ns_names

    @classmethod
    def _query_public_ns(cls, zone):
        """Ask public resolvers for the NS set the world sees for *zone*."""
        query_id = secrets.randbelow(0x10000)
        packet = cls._build_ns_query(zone, query_id)
        last_error = None
        for resolver in DELEGATION_RESOLVERS:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                sock.settimeout(4)
                sock.sendto(packet, (resolver, 53))
                data, _ = sock.recvfrom(4096)
                return cls._parse_ns_response(data, query_id)
            except (OSError, ValueError) as e:
                last_error = e
            finally:
                sock.close()
        raise OSError(f'All resolvers failed: {last_error}')

    @classmethod
    def check_delegation(cls, zone):
        """Best-effort: does the public NS set for the zone match ours?"""
        canonical = _canonical_zone(zone)
        if not canonical:
            return {'success': False, 'error': f'Invalid zone name: {zone!r}'}

        zone_ns = []
        detail = cls.get_zone(canonical)
        if detail.get('success'):
            for rrset in detail['zone'].get('rrsets', []):
                if rrset.get('type') == 'NS' and rrset.get('name') == canonical:
                    zone_ns = sorted(v.rstrip('.').lower() for v in rrset['records'])

        try:
            public_ns = sorted(set(cls._query_public_ns(canonical)))
        except (OSError, ValueError) as e:
            return {'success': True, 'checked': False, 'zone_ns': zone_ns,
                    'public_ns': [], 'delegated': None,
                    'note': f'Could not query public resolvers: {e}'}

        delegated = bool(public_ns) and set(public_ns) == set(zone_ns)
        note = None
        if not public_ns:
            note = ('No public NS records found — the domain is not delegated '
                    'to any nameserver yet. Set the NS (glue) records at your '
                    'registrar.')
        elif not delegated:
            note = ('The public NS set differs from this zone\'s NS records. '
                    'Update the nameservers at your registrar.')
        return {'success': True, 'checked': True, 'zone_ns': zone_ns,
                'public_ns': public_ns, 'delegated': delegated, 'note': note}
