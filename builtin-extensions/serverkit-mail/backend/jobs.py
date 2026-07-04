"""Background job handlers (serverkit-mail extension).

Registered via the manifest ``jobs`` block; each handler takes the ``job`` row
and must never raise (a raised handler fails the job loudly — these are
best-effort maintenance tasks).

* ``mail.preflight.run`` (:func:`run_preflight`) — re-check deliverability for the
  configured hostname on a daily schedule; notify admins if it regressed to
  failing.
* ``mail.queue.flush`` (:func:`flush_queue`) — ask Stalwart to retry its outbound
  queue.
"""
import logging

logger = logging.getLogger(__name__)

SLUG = 'serverkit-mail'


def run_preflight(job):
    """Re-run the deliverability preflight for the configured hostname.

    Reads the hostname from the plugin config store, re-runs preflight, and —
    when the verdict regressed from passing to failing — notifies admins. Never
    raises.
    """
    try:
        from app.plugins_sdk import config as plugin_config
        from .preflight_service import PreflightService

        cfg = plugin_config(SLUG)
        hostname = cfg.get('hostname')
        server_ip = cfg.get('server_ip')
        if not hostname:
            return {'skipped': True, 'reason': 'no hostname configured'}

        previous = PreflightService.latest()
        was_passing = bool(previous and previous.get('passed'))

        result = PreflightService.run(hostname, server_ip=server_ip)
        now_passing = bool(result and result.get('passed'))

        if was_passing and not now_passing:
            _notify_regression(hostname, result)

        return {'hostname': hostname, 'passed': now_passing,
                'regressed': was_passing and not now_passing}
    except Exception as e:  # noqa: BLE001 — a maintenance job must not crash the loop
        logger.warning('mail preflight job failed: %s', e)
        return {'error': str(e)}


def _notify_regression(hostname, result):
    try:
        from app.plugins_sdk import notify
        notify.send('mail.preflight_failed', to='admins',
                    data={'hostname': hostname, 'result': result},
                    category='system')
    except Exception as e:  # noqa: BLE001
        logger.debug('mail.preflight_failed notify failed: %s', e)


def flush_queue(job):
    """Best-effort flush of the Stalwart outbound queue. Never raises."""
    try:
        from .stalwart_service import StalwartService
        return StalwartService.flush_queue()
    except Exception as e:  # noqa: BLE001
        logger.warning('mail queue flush job failed: %s', e)
        return {'error': str(e)}
