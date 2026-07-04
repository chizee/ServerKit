"""Deliverability preflight checks (serverkit-mail extension).

Running a mail server that the world will *accept* mail from has hard host
prerequisites that a panel cannot fix for you. This service checks them and
persists the verdict; :class:`MailService` refuses to activate outbound sending
for a domain until the latest preflight ``passed`` (or an explicit force
override is logged).

Checks (all best-effort, individually monkeypatchable for tests):

* **PTR / reverse DNS** — the server IP's PTR record must resolve back to the
  mail hostname (``socket.gethostbyaddr``). Mismatched PTR is the #1 reason big
  providers reject mail.
* **Port-25 egress** — many VPS providers block outbound TCP :25. We try to open
  a connection to a public MX on :25 with a short timeout.
* **RBL / DNSBL** — query a couple of well-known blocklists for the reversed
  server IP; any hit means the IP is listed.
* **Local listening ports** — best-effort check that the mail ports are open
  locally.

On Windows / dev, every host-dependent check returns ``skipped`` and the overall
verdict is ``passed=False`` with a clear note. Nothing here ever raises.
"""
import json
import logging
import os
import socket

logger = logging.getLogger(__name__)

# A public MX we can dial on :25 to prove outbound egress is not blocked.
PORT25_PROBE_HOST = 'gmail-smtp-in.l.google.com'
PORT25_PROBE_PORT = 25
PORT25_TIMEOUT = 6

# DNSBLs queried for the reversed server IP.
RBL_ZONES = ('zen.spamhaus.org', 'bl.spamcop.net')

# Mail ports we expect to be listening locally once Stalwart is up.
LOCAL_PORTS = (25, 465, 587, 993)


class PreflightService:
    """Stateless deliverability preflight runner."""

    # ---------- individual checks (monkeypatchable) ----------

    @staticmethod
    def _check_ptr(hostname, server_ip):
        """Reverse-DNS: does the server IP's PTR match *hostname*?

        Returns ``(ok, ptr_value, note)``.
        """
        if os.name == 'nt':
            return None, None, 'skipped (not supported on this OS)'
        if not server_ip:
            return None, None, 'skipped (no server IP provided)'
        try:
            ptr_value = socket.gethostbyaddr(server_ip)[0]
        except (OSError, socket.herror) as e:
            return False, None, f'PTR lookup failed: {e}'
        ptr_norm = (ptr_value or '').strip().lower().rstrip('.')
        host_norm = (hostname or '').strip().lower().rstrip('.')
        ok = bool(host_norm) and ptr_norm == host_norm
        note = None if ok else f'PTR {ptr_norm!r} does not match hostname {host_norm!r}'
        return ok, ptr_value, note

    @staticmethod
    def _check_port25():
        """Outbound TCP :25 egress test against a public MX.

        Returns ``(ok, note)``.
        """
        if os.name == 'nt':
            return None, 'skipped (not supported on this OS)'
        try:
            conn = socket.create_connection(
                (PORT25_PROBE_HOST, PORT25_PROBE_PORT), timeout=PORT25_TIMEOUT)
            conn.close()
            return True, None
        except OSError as e:
            return False, (f'Could not open outbound :25 to {PORT25_PROBE_HOST} '
                           f'({e}) — your provider likely blocks port 25.')

    @staticmethod
    def _reverse_ip(server_ip):
        """Return the reversed dotted-quad of an IPv4 address, or None."""
        parts = (server_ip or '').split('.')
        if len(parts) != 4 or not all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
            return None
        return '.'.join(reversed(parts))

    @classmethod
    def _check_rbl(cls, server_ip):
        """Query the DNSBLs for the reversed server IP.

        Returns ``(ok, hits, note)`` — ``ok`` is True when the IP is on no list.
        """
        if os.name == 'nt':
            return None, [], 'skipped (not supported on this OS)'
        if not server_ip:
            return None, [], 'skipped (no server IP provided)'
        reversed_ip = cls._reverse_ip(server_ip)
        if not reversed_ip:
            return None, [], 'skipped (non-IPv4 address)'
        hits = []
        checked = 0
        for zone in RBL_ZONES:
            query = f'{reversed_ip}.{zone}'
            try:
                socket.gethostbyname(query)
                hits.append(zone)  # a resolvable A record == listed
                checked += 1
            except socket.gaierror:
                checked += 1  # NXDOMAIN == not listed (the good case)
            except OSError:
                continue  # transient resolver error — don't count it
        if checked == 0:
            return None, [], 'skipped (RBL resolvers unreachable)'
        ok = not hits
        note = None if ok else f'Listed on: {", ".join(hits)}'
        return ok, hits, note

    @staticmethod
    def _check_local_ports():
        """Best-effort: are the mail ports listening on localhost?

        Returns ``(ok, note)``. This is advisory only — a fresh install may not
        be running yet — so it never drives the pass/fail verdict on its own.
        """
        if os.name == 'nt':
            return None, 'skipped (not supported on this OS)'
        open_ports = []
        for port in LOCAL_PORTS:
            try:
                conn = socket.create_connection(('127.0.0.1', port), timeout=2)
                conn.close()
                open_ports.append(port)
            except OSError:
                continue
        ok = bool(open_ports)
        note = None if ok else 'No mail ports are listening locally yet.'
        return ok, note

    # ---------- orchestration ----------

    @classmethod
    def run(cls, hostname, server_ip=None):
        """Run all checks, persist a :class:`PreflightResult`, and return its dict.

        ``passed`` requires the *critical* checks (PTR, port-25 egress, RBL) to
        pass. Skipped checks (Windows/dev, missing IP) count as not-passed so a
        dev box never green-lights sending. Never raises.
        """
        hostname = (hostname or '').strip().lower().rstrip('.')

        ptr_ok, ptr_value, ptr_note = cls._check_ptr(hostname, server_ip)
        port25_ok, port25_note = cls._check_port25()
        rbl_ok, rbl_hits, rbl_note = cls._check_rbl(server_ip)
        ports_ok, ports_note = cls._check_local_ports()

        # Critical checks must be explicitly True (None/skipped => not passed).
        critical = [ptr_ok, port25_ok, rbl_ok]
        passed = all(c is True for c in critical)

        detail = {
            'ptr': {'ok': ptr_ok, 'value': ptr_value, 'note': ptr_note},
            'port25': {'ok': port25_ok, 'note': port25_note},
            'rbl': {'ok': rbl_ok, 'hits': rbl_hits, 'note': rbl_note},
            'ports': {'ok': ports_ok, 'note': ports_note},
            'critical_checks': ['ptr', 'port25', 'rbl'],
        }
        if os.name == 'nt':
            detail['dev_note'] = ('Host-dependent checks are skipped on this OS; '
                                  'run preflight on the target server before sending.')

        result = {
            'hostname': hostname,
            'server_ip': server_ip,
            'ptr_ok': bool(ptr_ok),
            'ptr_value': ptr_value,
            'port25_ok': bool(port25_ok),
            'rbl_ok': bool(rbl_ok),
            'rbl_hits': rbl_hits,
            'ports_ok': bool(ports_ok),
            'passed': passed,
            'detail': detail,
        }
        cls._persist(result)
        # Return the freshly persisted row's dict (falls back to the raw result).
        latest = cls.latest()
        return latest or {**result, 'rbl_hits': rbl_hits, 'detail': detail}

    @classmethod
    def _persist(cls, result):
        """Store a PreflightResult row. Best-effort; never raises."""
        try:
            from app import db
            from .models import PreflightResult
            row = PreflightResult(
                hostname=result.get('hostname'),
                server_ip=result.get('server_ip'),
                ptr_ok=result.get('ptr_ok'),
                ptr_value=result.get('ptr_value'),
                port25_ok=result.get('port25_ok'),
                rbl_ok=result.get('rbl_ok'),
                rbl_hits=json.dumps(result.get('rbl_hits') or []),
                ports_ok=result.get('ports_ok'),
                passed=result.get('passed'),
                detail=json.dumps(result.get('detail') or {}),
            )
            db.session.add(row)
            db.session.commit()
            return row
        except Exception as e:  # noqa: BLE001 — persistence is best-effort
            logger.warning('Preflight result could not be persisted: %s', e)
            try:
                from app import db
                db.session.rollback()
            except Exception:
                pass
            return None

    @classmethod
    def latest(cls):
        """Most recent PreflightResult as a dict, or None."""
        try:
            from .models import PreflightResult
            row = (PreflightResult.query
                   .order_by(PreflightResult.checked_at.desc(),
                             PreflightResult.id.desc())
                   .first())
            return row.to_dict() if row else None
        except Exception as e:  # noqa: BLE001
            logger.debug('Could not load latest preflight: %s', e)
            return None
