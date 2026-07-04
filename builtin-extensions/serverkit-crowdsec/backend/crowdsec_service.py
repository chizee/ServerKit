"""CrowdSec integration service (serverkit-crowdsec extension).

Read/write integration with a host-installed CrowdSec security engine via its
``cscli`` CLI — the same pattern as the core Fail2ban integration, packaged as
an extension:

* **Single choke-point** — every invocation goes through :meth:`_cscli`,
  which owns privilege escalation, timeouts, JSON parsing, and error shaping.
* **Best-effort, Linux-only** — on Windows (dev) or when ``cscli`` is absent,
  calls return a clean error dict instead of raising; the UI degrades to an
  install-guidance empty state. CrowdSec is never auto-installed.
* **Feature-detected allowlists** — the ``cscli allowlists`` subcommand only
  exists in newer CrowdSec releases; when the installed version lacks it the
  service reports ``supported: False`` and the UI shows an upgrade note.
"""
import ipaddress
import json
import logging
import os
import re
import subprocess

from app.utils.system import run_privileged, is_command_available, ServiceControl

logger = logging.getLogger(__name__)

CSCLI_TIMEOUT = 20
DOCS_URL = 'https://docs.crowdsec.net/docs/getting_started/install_crowdsec/'

# cscli-style durations: 4h, 30m, 1h30m, 7d ...
_DURATION_RE = re.compile(r'^(\d+[smhd])+$')
# Allowlist names stay argv/URL-safe.
_NAME_RE = re.compile(r'^[A-Za-z0-9_.-]+$')
# cobra's "no such subcommand" wording variants (feature detection).
_UNKNOWN_CMD_RE = re.compile(r'unknown (?:command|sub-?command)', re.IGNORECASE)


def _valid_ip_or_range(value):
    """True when *value* parses as an IP address or CIDR range."""
    if not value or not isinstance(value, str):
        return False
    try:
        if '/' in value:
            ipaddress.ip_network(value, strict=False)
        else:
            ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


class CrowdSecService:
    """Stateless wrapper around ``cscli``. All methods return plain dicts."""

    # ---------- availability ----------

    @classmethod
    def is_installed(cls):
        """True only on a Linux host where cscli is installed."""
        if os.name == 'nt':
            return False
        return is_command_available('cscli')

    # ---------- choke-point ----------

    @classmethod
    def _cscli(cls, args, timeout=CSCLI_TIMEOUT, parse_json=False):
        """Run ``cscli <args>`` and return a normalized result dict.

        Every cscli invocation in this service funnels through here so
        privilege escalation, timeouts, JSON parsing, and error shaping
        live in exactly one place.
        """
        if os.name == 'nt':
            return {'success': False,
                    'error': 'CrowdSec integration is not supported on Windows.'}
        if not is_command_available('cscli'):
            return {'success': False, 'not_installed': True,
                    'error': 'CrowdSec (cscli) is not installed on this host.'}

        cmd = ['cscli'] + list(args)
        try:
            result = run_privileged(cmd, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {'success': False,
                    'error': f'cscli timed out after {timeout}s'}
        except (OSError, subprocess.SubprocessError) as e:
            return {'success': False, 'error': f'Failed to run cscli: {e}'}

        out = {
            'success': result.returncode == 0,
            'returncode': result.returncode,
            'stdout': result.stdout or '',
            'stderr': result.stderr or '',
        }
        if not out['success']:
            out['error'] = (out['stderr'] or out['stdout'] or 'cscli failed').strip()
            return out

        if parse_json:
            raw = out['stdout'].strip()
            # cscli prints the literal string "null" for empty result sets.
            if raw in ('', 'null'):
                out['data'] = None
            else:
                try:
                    out['data'] = json.loads(raw)
                except ValueError:
                    out['success'] = False
                    out['error'] = 'cscli returned invalid JSON'
        return out

    # ---------- status ----------

    @classmethod
    def get_status(cls):
        """Installed / running / version / LAPI reachability, best-effort."""
        status = {
            'installed': cls.is_installed(),
            'running': False,
            'version': None,
            'lapi_ok': False,
            'allowlists_supported': False,
            'docs_url': DOCS_URL,
        }
        if not status['installed']:
            return status

        try:
            status['running'] = ServiceControl.is_active('crowdsec')
        except Exception:  # systemctl absent (container) — stay best-effort
            status['running'] = False

        # `cscli version` historically prints to stderr; scan both streams.
        res = cls._cscli(['version'])
        blob = (res.get('stdout', '') or '') + '\n' + (res.get('stderr', '') or '')
        m = re.search(r'version:?\s*v?([0-9][\w.+~-]*)', blob, re.IGNORECASE)
        if m:
            status['version'] = m.group(1)

        # LAPI reachability: exit 0 == the engine can talk to its Local API.
        lapi = cls._cscli(['lapi', 'status'])
        status['lapi_ok'] = bool(lapi.get('success'))

        status['allowlists_supported'] = cls.allowlists_supported()
        return status

    # ---------- decisions ----------

    @classmethod
    def list_decisions(cls, ip=None, scope=None, dtype=None):
        """Flattened active decisions (cscli nests them under alerts)."""
        args = ['decisions', 'list', '-o', 'json']
        if ip:
            args += ['--ip', ip]
        if scope:
            args += ['--scope', scope]
        if dtype:
            args += ['--type', dtype]
        res = cls._cscli(args, parse_json=True)
        if not res.get('success'):
            return res

        decisions = []
        for alert in res.get('data') or []:
            source = alert.get('source') or {}
            for d in alert.get('decisions') or []:
                decisions.append({
                    'id': d.get('id'),
                    'value': d.get('value'),
                    'scope': d.get('scope'),
                    'type': d.get('type'),
                    'origin': d.get('origin'),
                    'duration': d.get('duration'),
                    'until': d.get('until'),
                    'reason': d.get('scenario') or alert.get('scenario'),
                    'country': source.get('cn'),
                    'as_name': source.get('as_name'),
                    'created_at': alert.get('created_at'),
                })
        return {'success': True, 'decisions': decisions}

    @classmethod
    def add_decision(cls, ip, duration='4h', reason='Manual ban from ServerKit',
                     dtype='ban'):
        """Ban an IP or CIDR range (``cscli decisions add``)."""
        if not _valid_ip_or_range(ip):
            return {'success': False, 'error': f'Invalid IP address or range: {ip!r}'}
        if not _DURATION_RE.match(duration or ''):
            return {'success': False,
                    'error': f'Invalid duration (use e.g. 4h, 30m, 7d): {duration!r}'}
        target_flag = '--range' if '/' in ip else '--ip'
        res = cls._cscli(['decisions', 'add', target_flag, ip,
                          '--duration', duration,
                          '--reason', str(reason or 'Manual ban from ServerKit'),
                          '--type', str(dtype or 'ban')])
        if res.get('success'):
            return {'success': True, 'message': f'Decision added for {ip}'}
        return res

    @classmethod
    def delete_decision(cls, ip):
        """Remove all decisions for an IP or CIDR range."""
        if not _valid_ip_or_range(ip):
            return {'success': False, 'error': f'Invalid IP address or range: {ip!r}'}
        target_flag = '--range' if '/' in ip else '--ip'
        res = cls._cscli(['decisions', 'delete', target_flag, ip])
        if res.get('success'):
            return {'success': True, 'message': f'Decisions deleted for {ip}'}
        return res

    # ---------- alerts ----------

    @classmethod
    def list_alerts(cls, limit=50):
        """Recent alerts, normalized for the table UI."""
        try:
            limit = max(1, min(int(limit), 500))
        except (TypeError, ValueError):
            limit = 50
        res = cls._cscli(['alerts', 'list', '-o', 'json', '--limit', str(limit)],
                         parse_json=True)
        if not res.get('success'):
            return res

        alerts = []
        for a in res.get('data') or []:
            source = a.get('source') or {}
            alerts.append({
                'id': a.get('id'),
                'scenario': a.get('scenario'),
                'source': source.get('ip') or source.get('value'),
                'country': source.get('cn'),
                'as_name': source.get('as_name'),
                'events_count': a.get('events_count'),
                'decisions': len(a.get('decisions') or []),
                'created_at': a.get('created_at'),
            })
        return {'success': True, 'alerts': alerts}

    # ---------- allowlists (feature-detected) ----------

    @classmethod
    def _allowlists_probe(cls):
        """Run the cheapest allowlists command and return (supported, result)."""
        res = cls._cscli(['allowlists', 'list', '-o', 'json'], parse_json=True)
        if res.get('success'):
            return True, res
        blob = ' '.join([res.get('error', '') or '',
                         res.get('stderr', '') or '',
                         res.get('stdout', '') or ''])
        if _UNKNOWN_CMD_RE.search(blob):
            return False, res
        # Command exists but the call failed for another reason (LAPI down…).
        return True, res

    @classmethod
    def allowlists_supported(cls):
        """True when the installed cscli knows the ``allowlists`` subcommand."""
        supported, _ = cls._allowlists_probe()
        return supported

    _ALLOWLISTS_UNSUPPORTED_MSG = (
        'The installed CrowdSec version does not support centralized '
        'allowlists (cscli allowlists). Upgrade CrowdSec to manage '
        'allowlists from the panel.'
    )

    @classmethod
    def list_allowlists(cls):
        supported, res = cls._allowlists_probe()
        if not supported:
            return {'success': True, 'supported': False, 'allowlists': [],
                    'message': cls._ALLOWLISTS_UNSUPPORTED_MSG}
        if not res.get('success'):
            return res
        entries = res.get('data') or []
        if not isinstance(entries, list):
            entries = []
        return {'success': True, 'supported': True, 'allowlists': entries}

    @classmethod
    def inspect_allowlist(cls, name):
        if not _NAME_RE.match(name or ''):
            return {'success': False, 'error': f'Invalid allowlist name: {name!r}'}
        res = cls._cscli(['allowlists', 'inspect', name, '-o', 'json'],
                         parse_json=True)
        if not res.get('success'):
            return res
        return {'success': True, 'allowlist': res.get('data')}

    @classmethod
    def create_allowlist(cls, name, description=''):
        if not _NAME_RE.match(name or ''):
            return {'success': False,
                    'error': 'Allowlist name must be alphanumeric/dashes/underscores/dots.'}
        res = cls._cscli(['allowlists', 'create', name,
                          '--description', str(description or 'Managed by ServerKit')])
        if res.get('success'):
            return {'success': True, 'message': f'Allowlist {name} created'}
        return res

    @classmethod
    def add_allowlist_entry(cls, name, value, expiration=None, comment=None):
        if not _NAME_RE.match(name or ''):
            return {'success': False, 'error': f'Invalid allowlist name: {name!r}'}
        if not _valid_ip_or_range(value):
            return {'success': False,
                    'error': f'Invalid IP address or range: {value!r}'}
        args = ['allowlists', 'add', name, value]
        if expiration:
            if not _DURATION_RE.match(str(expiration)):
                return {'success': False,
                        'error': f'Invalid expiration (use e.g. 24h, 7d): {expiration!r}'}
            args += ['--expiration', str(expiration)]
        if comment:
            args += ['--comment', str(comment)]
        res = cls._cscli(args)
        if res.get('success'):
            return {'success': True, 'message': f'Added {value} to {name}'}
        return res

    @classmethod
    def remove_allowlist_entry(cls, name, value):
        if not _NAME_RE.match(name or ''):
            return {'success': False, 'error': f'Invalid allowlist name: {name!r}'}
        if not _valid_ip_or_range(value):
            return {'success': False,
                    'error': f'Invalid IP address or range: {value!r}'}
        res = cls._cscli(['allowlists', 'remove', name, value])
        if res.get('success'):
            return {'success': True, 'message': f'Removed {value} from {name}'}
        return res

    # ---------- metrics ----------

    @classmethod
    def get_metrics(cls):
        """Raw engine metrics, best-effort (shape varies across versions)."""
        res = cls._cscli(['metrics', '-o', 'json'], parse_json=True)
        if not res.get('success'):
            return res
        return {'success': True, 'metrics': res.get('data')}
