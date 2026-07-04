"""One-shot "doctor" health sweep + explicit batch repair.

Aggregates the drift report (drift_service) with a handful of cheap host
health probes into a single ``{'checks': [...], 'ran_at': ...}`` report the
Monitoring → Doctor tab renders. Everything is best-effort and bounded — the
doctor is interactive (the API runs it synchronously), so no probe may hang.

Nothing here repairs anything automatically: :meth:`DoctorService.repair`
runs only for the explicit items the operator selected.
"""
import json
import logging
import sys
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

DOCTOR_JOB_KIND = 'doctor.run'
LAST_REPORT_KEY = 'doctor_last_report'

# Core host services the doctor probes and is allowed to restart on demand.
CORE_SERVICES = ('nginx', 'docker')

CERT_WARN_DAYS = 14
DISK_WARN_FREE_PCT = 10.0
DISK_FAIL_FREE_PCT = 5.0

# Cap for the synchronous probes that shell out (systemctl is-active).
PROBE_TIMEOUT_SECONDS = 10


def _check(key, title, status, detail, repairable=False, repair_ref=None):
    return {
        'key': key,
        'title': title,
        'status': status,  # 'ok' | 'warn' | 'fail'
        'detail': detail,
        'repairable': bool(repairable),
        'repair_ref': repair_ref,
    }


class DoctorService:
    """Run the health sweep, store the last report, batch-repair on demand."""

    # ------------------------------------------------------------------ #
    # Sub-checks (each best-effort; a probe failure = a 'warn' entry, never
    # an exception out of run()).
    # ------------------------------------------------------------------ #

    @classmethod
    def _drift_checks(cls):
        from app.services.drift_service import DriftService
        checks = []
        try:
            results = DriftService.check_all()
        except Exception as e:  # noqa: BLE001
            return [_check('drift', 'Configuration drift', 'warn',
                           f'Drift sweep failed: {e}')]
        for r in results:
            key = f"drift.{r['type']}.{r['id']}" if r['id'] is not None else f"drift.{r['type']}"
            title = f"Drift: {r['name']}"
            if r['status'] == 'in_sync':
                checks.append(_check(key, title, 'ok', 'Matches the expected configuration.'))
            elif r['status'] in ('drifted', 'missing'):
                detail = ('Managed file is missing on disk.' if r['status'] == 'missing'
                          else 'On-disk file differs from what ServerKit would write.')
                entry = _check(
                    key, title, 'warn', detail, repairable=True,
                    repair_ref={'kind': 'drift', 'type': r['type'], 'id': r['id']},
                )
                entry['diff'] = r.get('diff')
                checks.append(entry)
            else:  # error
                checks.append(_check(key, title, 'warn',
                                     r.get('detail') or 'Check could not run.'))
        return checks

    @classmethod
    def _service_checks(cls):
        checks = []
        if not sys.platform.startswith('linux'):
            for name in CORE_SERVICES:
                checks.append(_check(f'service.{name}', f'{name} service', 'warn',
                                     'unsupported on this host'))
            return checks
        from app.utils.system import ServiceControl
        for name in CORE_SERVICES:
            try:
                active = ServiceControl.is_active(name)
            except Exception as e:  # noqa: BLE001
                checks.append(_check(f'service.{name}', f'{name} service', 'warn',
                                     f'Status probe failed: {e}'))
                continue
            if active:
                checks.append(_check(f'service.{name}', f'{name} service', 'ok', 'Running.'))
            else:
                checks.append(_check(
                    f'service.{name}', f'{name} service', 'fail', 'Not running.',
                    repairable=True, repair_ref={'kind': 'service', 'name': name},
                ))
        return checks

    @classmethod
    def _cert_check(cls):
        """Nearest tracked certificate expiry (Domain.ssl_expires_at)."""
        try:
            from app.models.domain import Domain
            rows = (Domain.query
                    .filter(Domain.ssl_expires_at.isnot(None))
                    .order_by(Domain.ssl_expires_at.asc())
                    .all())
        except Exception as e:  # noqa: BLE001
            return _check('certs.expiry', 'Certificate expiry', 'warn',
                          f'Could not read certificate data: {e}')
        if not rows:
            return _check('certs.expiry', 'Certificate expiry', 'ok',
                          'No certificates tracked.')
        now = datetime.utcnow()
        soon = [d for d in rows if d.ssl_expires_at <= now + timedelta(days=CERT_WARN_DAYS)]
        expired = [d for d in soon if d.ssl_expires_at <= now]
        if expired:
            names = ', '.join(d.name for d in expired[:5])
            return _check('certs.expiry', 'Certificate expiry', 'fail',
                          f'Expired certificate(s): {names}')
        if soon:
            nearest = soon[0]
            days = max(0, (nearest.ssl_expires_at - now).days)
            return _check('certs.expiry', 'Certificate expiry', 'warn',
                          f'{len(soon)} certificate(s) expire within {CERT_WARN_DAYS} days '
                          f'(nearest: {nearest.name} in {days}d).')
        nearest = rows[0]
        return _check('certs.expiry', 'Certificate expiry', 'ok',
                      f'Nearest expiry: {nearest.name} on '
                      f'{nearest.ssl_expires_at.date().isoformat()}.')

    @classmethod
    def _disk_check(cls):
        try:
            import psutil
            usage = psutil.disk_usage('/')
            free_pct = 100.0 - usage.percent
        except Exception as e:  # noqa: BLE001
            return _check('disk.headroom', 'Disk headroom', 'warn',
                          f'Could not read disk usage: {e}')
        detail = f'{free_pct:.1f}% free on /.'
        if free_pct < DISK_FAIL_FREE_PCT:
            return _check('disk.headroom', 'Disk headroom', 'fail', detail)
        if free_pct < DISK_WARN_FREE_PCT:
            return _check('disk.headroom', 'Disk headroom', 'warn', detail)
        return _check('disk.headroom', 'Disk headroom', 'ok', detail)

    @classmethod
    def _db_check(cls):
        try:
            from sqlalchemy import text
            from app import db
            db.session.execute(text('SELECT 1'))
            return _check('db.reachable', 'Database', 'ok', 'Reachable.')
        except Exception as e:  # noqa: BLE001
            return _check('db.reachable', 'Database', 'fail', f'Query failed: {e}')

    # ------------------------------------------------------------------ #
    # Sweep
    # ------------------------------------------------------------------ #

    @classmethod
    def run(cls):
        """Run the full sweep synchronously and store the report.

        Returns ``{'checks': [...], 'ran_at': iso}``.
        """
        checks = []
        checks += cls._drift_checks()
        checks += cls._service_checks()
        checks.append(cls._cert_check())
        checks.append(cls._disk_check())
        checks.append(cls._db_check())
        report = {
            'checks': checks,
            'ran_at': datetime.utcnow().isoformat() + 'Z',
        }
        cls.store_report(report)
        return report

    @classmethod
    def store_report(cls, report):
        try:
            from app.services.settings_service import SettingsService
            SettingsService.set(LAST_REPORT_KEY, json.dumps(report))
        except Exception as e:  # noqa: BLE001 — storage is best-effort
            logger.warning('could not store doctor report: %s', e)

    @classmethod
    def get_last_report(cls):
        from app.services.settings_service import SettingsService
        raw = SettingsService.get(LAST_REPORT_KEY)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------ #
    # Batch repair (explicit only)
    # ------------------------------------------------------------------ #

    @classmethod
    def repair(cls, items):
        """Repair an explicit list of items.

        ``items``: ``[{'kind': 'drift', 'type': ..., 'id': ...} |
        {'kind': 'service', 'name': ...}]``. Returns per-item results (same
        order), each carrying the input item plus ``success``/detail fields.
        """
        results = []
        for item in items or []:
            kind = (item or {}).get('kind')
            if kind == 'drift':
                from app.services.drift_service import DriftService
                res = DriftService.repair(item.get('type'), item.get('id'))
                results.append({'item': item, **res})
            elif kind == 'service':
                results.append({'item': item, **cls._restart_service(item.get('name'))})
            else:
                results.append({'item': item, 'success': False,
                                'error': f'Unknown repair kind: {kind}'})
        return results

    @classmethod
    def _restart_service(cls, name):
        if name not in CORE_SERVICES:
            return {'success': False, 'error': f'Service not repairable: {name}'}
        if not sys.platform.startswith('linux'):
            return {'success': False, 'error': 'unsupported on this host'}
        try:
            from app.utils.system import ServiceControl
            proc = ServiceControl.restart(name, timeout=60)
            if proc.returncode == 0:
                return {'success': True, 'restarted': name}
            return {'success': False, 'error': (proc.stderr or '').strip()
                    or f'systemctl restart {name} failed'}
        except Exception as e:  # noqa: BLE001
            return {'success': False, 'error': str(e)}

    # ------------------------------------------------------------------ #
    # Job plumbing
    # ------------------------------------------------------------------ #

    @classmethod
    def run_doctor_job(cls, job):
        """Job handler for ``doctor.run`` (background variant of run())."""
        report = cls.run()
        counts = {}
        for c in report['checks']:
            counts[c['status']] = counts.get(c['status'], 0) + 1
        return {'ran_at': report['ran_at'], 'counts': counts}

    @classmethod
    def register_jobs(cls):
        """Register the doctor handler with the job registry.
        Called once at app startup (see app/__init__.py)."""
        from app.jobs import registry
        registry.register(DOCTOR_JOB_KIND, cls.run_doctor_job, replace=True)
