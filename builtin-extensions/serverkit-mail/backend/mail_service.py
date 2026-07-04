"""DB <-> Stalwart orchestration (serverkit-mail extension).

The panel's tables (:mod:`.models`) are the source of truth for what mail objects
*should* exist; this service is the reconcile layer. Every mutation:

1. Writes the panel DB (this always succeeds, or returns a clean 400).
2. Best-effort reconciles the change to Stalwart via :class:`StalwartService`.
3. Records the outcome on the row's ``sync_state`` / ``sync_error``.

A Stalwart failure therefore never loses panel state: the row exists with
``sync_state='error'`` and the call returns ``{success: True, sync_state:
'error', ...}`` so the panel can surface and later re-sync the drift. Everything
is wrapped so a missing Stalwart/Docker (dev) never raises.

Activation gate: :meth:`set_domain_active` refuses to activate a domain (which
enables outbound sending) unless the latest :class:`PreflightResult` passed, or an
explicit ``force=True`` override is passed (which is audit-logged).
"""
import logging

logger = logging.getLogger(__name__)


class MailService:
    """Stateless DB/Stalwart reconcile orchestration."""

    # ---------- helpers ----------

    @staticmethod
    def _db():
        from app import db
        return db

    @staticmethod
    def _models():
        from . import models
        return models

    @staticmethod
    def _stalwart():
        from .stalwart_service import StalwartService
        return StalwartService

    @classmethod
    def _apply_sync(cls, row, result):
        """Fold a StalwartService reconcile *result* into a row's sync state."""
        if result.get('success'):
            row.sync_state = 'synced'
            row.sync_error = None
        else:
            row.sync_state = 'error'
            row.sync_error = result.get('error') or 'Stalwart sync failed'
        return row

    @staticmethod
    def _norm(value):
        return (value or '').strip().lower().rstrip('.')

    # ---------- status ----------

    @classmethod
    def get_status(cls):
        """Engine status merged with the latest deliverability preflight."""
        status = cls._stalwart().get_status()
        try:
            from .preflight_service import PreflightService
            status['preflight'] = PreflightService.latest()
        except Exception as e:  # noqa: BLE001
            logger.debug('preflight latest failed: %s', e)
            status['preflight'] = None
        try:
            from .models import MailDomain
            status['domains_count'] = MailDomain.query.count()
        except Exception:  # noqa: BLE001
            status['domains_count'] = 0
        return status

    # ---------- domains ----------

    @classmethod
    def list_domains(cls):
        MailDomain = cls._models().MailDomain
        return [d.to_dict() for d in MailDomain.query.order_by(MailDomain.name).all()]

    @classmethod
    def get_domain(cls, domain_id):
        MailDomain = cls._models().MailDomain
        row = MailDomain.query.get(domain_id)
        return row.to_dict() if row else None

    @classmethod
    def add_domain(cls, name, catch_all_target=None):
        db = cls._db()
        MailDomain = cls._models().MailDomain
        name = cls._norm(name)
        if not name or '.' not in name:
            return {'success': False, 'error': f'Invalid domain name: {name!r}'}
        if MailDomain.query.filter_by(name=name).first():
            return {'success': False, 'error': f'Domain {name} already exists'}
        row = MailDomain(name=name,
                         catch_all_target=(catch_all_target or '').strip() or None,
                         is_active=False, sync_state='pending')
        try:
            db.session.add(row)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            return {'success': False, 'error': str(e)}

        result = cls._safe(lambda: cls._stalwart().upsert_domain(name))
        cls._apply_sync(row, result)
        db.session.commit()
        return {'success': True, 'domain': row.to_dict(),
                'sync_state': row.sync_state, 'sync_error': row.sync_error}

    @classmethod
    def update_domain(cls, domain_id, is_active=None, catch_all_target=None):
        """Update mutable domain fields (catch-all + activation).

        Activation is delegated to :meth:`set_domain_active` so the preflight
        gate cannot be bypassed here.
        """
        db = cls._db()
        MailDomain = cls._models().MailDomain
        row = MailDomain.query.get(domain_id)
        if not row:
            return {'success': False, 'error': 'Domain not found'}

        if catch_all_target is not None:
            row.catch_all_target = (catch_all_target or '').strip() or None
            db.session.commit()

        if is_active is not None:
            return cls.set_domain_active(domain_id, bool(is_active))

        return {'success': True, 'domain': row.to_dict()}

    @classmethod
    def set_domain_active(cls, domain_id, active, force=False):
        """Activate/deactivate a domain. Activation enables outbound sending and
        is **gated** on the latest preflight passing, unless ``force=True`` (which
        is audit-logged)."""
        db = cls._db()
        MailDomain = cls._models().MailDomain
        row = MailDomain.query.get(domain_id)
        if not row:
            return {'success': False, 'error': 'Domain not found'}

        if active:
            from .preflight_service import PreflightService
            latest = None
            try:
                latest = PreflightService.latest()
            except Exception as e:  # noqa: BLE001
                logger.debug('preflight check failed during activation: %s', e)
            passed = bool(latest and latest.get('passed'))
            if not passed and not force:
                return {'success': False, 'code': 'preflight_required',
                        'error': 'Deliverability preflight has not passed. Run '
                                 'preflight and resolve any failures, or activate '
                                 'with force to override.',
                        'preflight': latest}
            if not passed and force:
                cls._audit('mail.domain.activate_forced', row.id, {
                    'domain': row.name,
                    'preflight_passed': passed,
                })

        row.is_active = bool(active)
        db.session.commit()

        # Reconcile: ensure the domain principal exists when activating.
        if active:
            result = cls._safe(lambda: cls._stalwart().upsert_domain(row.name))
            cls._apply_sync(row, result)
            db.session.commit()

        return {'success': True, 'domain': row.to_dict(),
                'sync_state': row.sync_state, 'sync_error': row.sync_error}

    @classmethod
    def remove_domain(cls, domain_id):
        db = cls._db()
        MailDomain = cls._models().MailDomain
        row = MailDomain.query.get(domain_id)
        if not row:
            return {'success': False, 'error': 'Domain not found'}
        name = row.name
        # Best-effort Stalwart cleanup before the DB delete (cascade removes
        # mailboxes/forwarders/autoresponders panel-side).
        cls._safe(lambda: cls._stalwart().delete_domain(name))
        try:
            from .mail_backup import unregister_backup_policy
            unregister_backup_policy(row)
        except Exception as e:  # noqa: BLE001
            logger.debug('backup unregister failed: %s', e)
        try:
            db.session.delete(row)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            return {'success': False, 'error': str(e)}
        return {'success': True, 'message': f'Domain {name} removed'}

    # ---------- mailboxes ----------

    @classmethod
    def list_mailboxes(cls, domain_id):
        Mailbox = cls._models().Mailbox
        rows = Mailbox.query.filter_by(domain_id=domain_id).order_by(Mailbox.local_part).all()
        return [m.to_dict() for m in rows]

    @classmethod
    def get_mailbox(cls, mailbox_id):
        Mailbox = cls._models().Mailbox
        row = Mailbox.query.get(mailbox_id)
        return row.to_dict() if row else None

    @classmethod
    def add_mailbox(cls, domain_id, local_part, password, quota_mb=0, display_name=None):
        """Create a mailbox. ``password`` is required (set on Stalwart only) and is
        NEVER persisted panel-side."""
        db = cls._db()
        models = cls._models()
        MailDomain, Mailbox = models.MailDomain, models.Mailbox
        domain = MailDomain.query.get(domain_id)
        if not domain:
            return {'success': False, 'error': 'Domain not found'}
        local_part = (local_part or '').strip().lower()
        if not local_part or '@' in local_part:
            return {'success': False, 'error': f'Invalid local part: {local_part!r}'}
        if not password:
            return {'success': False, 'error': 'A password is required'}
        if Mailbox.query.filter_by(domain_id=domain_id, local_part=local_part).first():
            return {'success': False,
                    'error': f'Mailbox {local_part}@{domain.name} already exists'}

        row = Mailbox(domain_id=domain_id, local_part=local_part,
                      quota_mb=int(quota_mb or 0),
                      display_name=(display_name or '').strip() or None,
                      is_active=True, sync_state='pending')
        try:
            db.session.add(row)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            return {'success': False, 'error': str(e)}

        email = f'{local_part}@{domain.name}'
        result = cls._safe(lambda: cls._stalwart().upsert_account(
            email, password=password, quota_mb=row.quota_mb, display_name=row.display_name))
        cls._apply_sync(row, result)
        db.session.commit()
        # password intentionally discarded here — never stored.
        return {'success': True, 'mailbox': row.to_dict(),
                'sync_state': row.sync_state, 'sync_error': row.sync_error}

    @classmethod
    def update_mailbox(cls, mailbox_id, quota_mb=None, is_active=None, display_name=None):
        db = cls._db()
        Mailbox = cls._models().Mailbox
        row = Mailbox.query.get(mailbox_id)
        if not row:
            return {'success': False, 'error': 'Mailbox not found'}
        if quota_mb is not None:
            row.quota_mb = int(quota_mb)
        if display_name is not None:
            row.display_name = (display_name or '').strip() or None
        if is_active is not None:
            row.is_active = bool(is_active)
        db.session.commit()

        result = cls._safe(lambda: cls._stalwart().upsert_account(
            row.email, quota_mb=row.quota_mb, display_name=row.display_name))
        cls._apply_sync(row, result)
        db.session.commit()
        return {'success': True, 'mailbox': row.to_dict(),
                'sync_state': row.sync_state, 'sync_error': row.sync_error}

    @classmethod
    def set_mailbox_password(cls, mailbox_id, password):
        db = cls._db()
        Mailbox = cls._models().Mailbox
        row = Mailbox.query.get(mailbox_id)
        if not row:
            return {'success': False, 'error': 'Mailbox not found'}
        if not password:
            return {'success': False, 'error': 'A password is required'}
        result = cls._safe(lambda: cls._stalwart().set_password(row.email, password))
        cls._apply_sync(row, result)
        db.session.commit()
        return {'success': True, 'sync_state': row.sync_state,
                'sync_error': row.sync_error}

    @classmethod
    def remove_mailbox(cls, mailbox_id):
        db = cls._db()
        Mailbox = cls._models().Mailbox
        row = Mailbox.query.get(mailbox_id)
        if not row:
            return {'success': False, 'error': 'Mailbox not found'}
        email = row.email
        cls._safe(lambda: cls._stalwart().delete_account(email))
        try:
            db.session.delete(row)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            return {'success': False, 'error': str(e)}
        return {'success': True, 'message': f'Mailbox {email} removed'}

    # ---------- autoresponder ----------

    @classmethod
    def get_autoresponder(cls, mailbox_id):
        models = cls._models()
        Mailbox, Autoresponder = models.Mailbox, models.Autoresponder
        if not Mailbox.query.get(mailbox_id):
            return None
        row = Autoresponder.query.filter_by(mailbox_id=mailbox_id).first()
        if row:
            return row.to_dict()
        # A not-yet-configured autoresponder reads as a disabled shell.
        return {'mailbox_id': mailbox_id, 'enabled': False, 'subject': None,
                'body': None, 'start_at': None, 'end_at': None}

    @classmethod
    def set_autoresponder(cls, mailbox_id, enabled=None, subject=None, body=None,
                          start_at=None, end_at=None):
        db = cls._db()
        models = cls._models()
        Mailbox, Autoresponder = models.Mailbox, models.Autoresponder
        if not Mailbox.query.get(mailbox_id):
            return {'success': False, 'error': 'Mailbox not found'}
        row = Autoresponder.query.filter_by(mailbox_id=mailbox_id).first()
        if not row:
            row = Autoresponder(mailbox_id=mailbox_id)
            db.session.add(row)
        if enabled is not None:
            row.enabled = bool(enabled)
        if subject is not None:
            row.subject = subject
        if body is not None:
            row.body = body
        if start_at is not None:
            row.start_at = cls._parse_dt(start_at)
        if end_at is not None:
            row.end_at = cls._parse_dt(end_at)
        try:
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            return {'success': False, 'error': str(e)}
        return {'success': True, 'autoresponder': row.to_dict()}

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        if hasattr(value, 'isoformat'):
            return value
        from datetime import datetime
        try:
            return datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None

    # ---------- forwarders ----------

    @classmethod
    def list_forwarders(cls, domain_id):
        Forwarder = cls._models().Forwarder
        rows = Forwarder.query.filter_by(domain_id=domain_id).order_by(
            Forwarder.source_local_part).all()
        return [f.to_dict() for f in rows]

    @classmethod
    def add_forwarder(cls, domain_id, source_local_part, destination, keep_copy=False):
        db = cls._db()
        models = cls._models()
        MailDomain, Forwarder = models.MailDomain, models.Forwarder
        domain = MailDomain.query.get(domain_id)
        if not domain:
            return {'success': False, 'error': 'Domain not found'}
        source_local_part = (source_local_part or '').strip().lower()
        destination = (destination or '').strip()
        if not source_local_part or '@' in source_local_part:
            return {'success': False, 'error': f'Invalid source: {source_local_part!r}'}
        if not destination:
            return {'success': False, 'error': 'A destination is required'}
        row = Forwarder(domain_id=domain_id, source_local_part=source_local_part,
                        destination=destination, keep_copy=bool(keep_copy),
                        is_active=True, sync_state='pending')
        try:
            db.session.add(row)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            return {'success': False, 'error': str(e)}

        # Forwarders map to an aliased principal on Stalwart; reconcile best-effort.
        email = f'{source_local_part}@{domain.name}'
        result = cls._safe(lambda: cls._stalwart().upsert_account(email))
        cls._apply_sync(row, result)
        db.session.commit()
        return {'success': True, 'forwarder': row.to_dict(),
                'sync_state': row.sync_state, 'sync_error': row.sync_error}

    @classmethod
    def remove_forwarder(cls, forwarder_id):
        db = cls._db()
        Forwarder = cls._models().Forwarder
        row = Forwarder.query.get(forwarder_id)
        if not row:
            return {'success': False, 'error': 'Forwarder not found'}
        try:
            db.session.delete(row)
            db.session.commit()
        except Exception as e:  # noqa: BLE001
            db.session.rollback()
            return {'success': False, 'error': str(e)}
        return {'success': True, 'message': 'Forwarder removed'}

    # ---------- internals ----------

    @staticmethod
    def _safe(fn):
        """Run a best-effort Stalwart reconcile call; never raise."""
        try:
            result = fn()
            return result if isinstance(result, dict) else {'success': bool(result)}
        except Exception as e:  # noqa: BLE001
            logger.debug('Stalwart reconcile call failed: %s', e)
            return {'success': False, 'error': str(e)}

    @staticmethod
    def _audit(action, target_id, details):
        try:
            from app.plugins_sdk import audit
            audit(action, 'mail_domain', target_id=target_id, details=details)
        except Exception as e:  # noqa: BLE001
            logger.debug('audit %s failed: %s', action, e)
