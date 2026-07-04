"""Register the mail data directory as a backup policy (serverkit-mail extension).

Thin, best-effort binder over the core :class:`BackupPolicyService`: a mail
domain's maildir lives under the Stalwart data dir, so we register that path as a
``files`` backup target with a daily schedule. Everything is wrapped so a missing
BackupPolicyService (or a dev shell without the job bus) is non-fatal.
"""
import logging

from .stalwart_service import DATA_DIR

logger = logging.getLogger(__name__)


def register_backup_policy(domain_row):
    """Register/enable a daily files backup of the mail data dir for *domain_row*.

    Best-effort: returns ``{success, ...}`` and never raises.
    """
    try:
        from app.services.backup_policy_service import BackupPolicyService
    except Exception as e:  # noqa: BLE001
        logger.debug('BackupPolicyService unavailable, skipping mail backup: %s', e)
        return {'success': False, 'skipped': True, 'error': str(e)}
    try:
        policy = BackupPolicyService.get_or_create_policy(
            target_type='files',
            target_id=domain_row.id,
            target_subtype='pathlist',
            target_meta={'label': f'mail:{domain_row.name}', 'paths': [DATA_DIR]},
        )
        BackupPolicyService.update_policy(policy, {
            'enabled': True,
            'schedule_cron': '0 3 * * *',  # daily at 03:00
        })
        return {'success': True, 'policy_id': policy.id}
    except Exception as e:  # noqa: BLE001
        logger.warning('Could not register mail backup policy for %s: %s',
                       getattr(domain_row, 'name', '?'), e)
        return {'success': False, 'error': str(e)}


def unregister_backup_policy(domain_row):
    """Disable the mail backup policy for *domain_row*. Best-effort; never raises.

    The policy row (and its history) is intentionally left in place — only the
    schedule is disabled — so a re-added domain keeps its backup lineage.
    """
    try:
        from app.services.backup_policy_service import BackupPolicyService
        policy = BackupPolicyService.get_policy('files', domain_row.id)
        if not policy:
            return {'success': True, 'skipped': True}
        BackupPolicyService.update_policy(policy, {'enabled': False})
        return {'success': True, 'policy_id': policy.id}
    except Exception as e:  # noqa: BLE001
        logger.debug('Could not unregister mail backup policy: %s', e)
        return {'success': False, 'error': str(e)}
