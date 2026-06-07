"""Service for event emission and webhook delivery."""
import hashlib
import hmac
import json
import logging
import time
import threading
import uuid
from datetime import datetime, timedelta

import requests as http_requests

from app import db
from app.models.event_subscription import EventSubscription, EventDelivery

logger = logging.getLogger(__name__)

# Mapping from audit log actions to event types
AUDIT_TO_EVENT = {
    'app.create': 'app.created',
    'app.update': 'app.updated',
    'app.delete': 'app.deleted',
    'app.start': 'app.started',
    'app.stop': 'app.stopped',
    'app.restart': 'app.restarted',
    'app.deploy': 'app.deployed',
    'backup.create': 'backup.created',
    'backup.restore': 'backup.restored',
    'user.create': 'user.created',
    'user.login': 'user.login',
    'api_key.create': 'api_key.created',
    'api_key.revoke': 'api_key.revoked',
}

# Available events catalog
EVENT_CATALOG = [
    {'type': 'app.created', 'category': 'Applications', 'description': 'An application was created'},
    {'type': 'app.updated', 'category': 'Applications', 'description': 'An application was updated'},
    {'type': 'app.deleted', 'category': 'Applications', 'description': 'An application was deleted'},
    {'type': 'app.started', 'category': 'Applications', 'description': 'An application was started'},
    {'type': 'app.stopped', 'category': 'Applications', 'description': 'An application was stopped'},
    {'type': 'app.restarted', 'category': 'Applications', 'description': 'An application was restarted'},
    {'type': 'app.deployed', 'category': 'Applications', 'description': 'An application was deployed'},
    {'type': 'container.started', 'category': 'Docker', 'description': 'A container was started'},
    {'type': 'container.stopped', 'category': 'Docker', 'description': 'A container was stopped'},
    {'type': 'backup.created', 'category': 'Backups', 'description': 'A backup was created'},
    {'type': 'backup.restored', 'category': 'Backups', 'description': 'A backup was restored'},
    {'type': 'user.created', 'category': 'Users', 'description': 'A user was created'},
    {'type': 'user.login', 'category': 'Users', 'description': 'A user logged in'},
    {'type': 'security.alert', 'category': 'Security', 'description': 'A security alert was triggered'},
    {'type': 'ssl.expiring', 'category': 'SSL', 'description': 'An SSL certificate is expiring soon'},
    {'type': 'domain.created', 'category': 'Domains', 'description': 'A domain was created'},
    {'type': 'domain.deleted', 'category': 'Domains', 'description': 'A domain was deleted'},
    {'type': 'api_key.created', 'category': 'API', 'description': 'An API key was created'},
    {'type': 'api_key.revoked', 'category': 'API', 'description': 'An API key was revoked'},
    {'type': 'wordpress.site_down', 'category': 'WordPress', 'description': 'A WordPress site failed its health check'},
    {'type': 'wordpress.site_up', 'category': 'WordPress', 'description': 'A WordPress site recovered after a failed health check'},
    {'type': 'wordpress.created', 'category': 'WordPress', 'description': 'A WordPress site was created'},
    {'type': 'wordpress.deleted', 'category': 'WordPress', 'description': 'A WordPress site was deleted'},
    {'type': 'wordpress.backup_completed', 'category': 'WordPress', 'description': 'A WordPress site backup/snapshot completed'},
    {'type': 'wordpress.updated', 'category': 'WordPress', 'description': 'A WordPress safe-update completed'},
    {'type': 'wordpress.update_rolled_back', 'category': 'WordPress', 'description': 'A WordPress update was auto-rolled-back'},
    {'type': 'wordpress.deployed', 'category': 'WordPress', 'description': 'A WordPress git deploy completed'},
    {'type': 'wordpress.deploy_failed', 'category': 'WordPress', 'description': 'A WordPress git deploy failed'},
]


class EventService:
    """Service for emitting events and delivering webhooks."""

    @staticmethod
    def get_available_events():
        """Return the event catalog."""
        return EVENT_CATALOG

    @staticmethod
    def emit_wp(event_type, site, **extra):
        """Emit a wordpress.* lifecycle event with a standard payload derived from a
        WordPressSite. Best-effort — never raises into the caller (so emitting an
        event can never break the WP operation that triggered it)."""
        try:
            payload = {'event': event_type, 'timestamp': datetime.utcnow().isoformat()}
            if site is not None:
                payload['site_id'] = getattr(site, 'id', None)
                app = getattr(site, 'application', None)
                payload['site_name'] = app.name if app else f'site {getattr(site, "id", "?")}'
            payload.update(extra)
            EventService.emit(event_type, payload)
        except Exception as e:
            logger.error(f'Failed to emit {event_type}: {e}')

    @staticmethod
    def emit(event_type, payload, user_id=None):
        """Emit an event to all matching subscriptions."""
        subscriptions = EventSubscription.query.filter_by(is_active=True).all()
        matching = [s for s in subscriptions if s.matches_event(event_type)]

        if not matching:
            return

        for sub in matching:
            delivery = EventDelivery(
                subscription_id=sub.id,
                event_type=event_type,
                status=EventDelivery.STATUS_PENDING,
            )
            delivery.set_payload(payload)
            db.session.add(delivery)

        db.session.commit()

        # Dispatch deliveries in background
        for sub in matching:
            pending = EventDelivery.query.filter_by(
                subscription_id=sub.id,
                event_type=event_type,
                status=EventDelivery.STATUS_PENDING,
            ).order_by(EventDelivery.created_at.desc()).first()

            if pending:
                thread = threading.Thread(
                    target=EventService._deliver_in_thread,
                    args=(pending.id,),
                    daemon=True,
                )
                thread.start()

    @staticmethod
    def emit_for_audit(action, target_type, target_id, details, user_id):
        """Emit an event based on an audit log action."""
        event_type = AUDIT_TO_EVENT.get(action)
        if not event_type:
            return

        payload = {
            'event': event_type,
            'timestamp': datetime.utcnow().isoformat(),
            'target_type': target_type,
            'target_id': target_id,
            'user_id': user_id,
            'details': details or {},
        }

        try:
            EventService.emit(event_type, payload, user_id)
        except Exception as e:
            logger.error(f'Failed to emit event {event_type}: {e}')

    @staticmethod
    def _deliver_in_thread(delivery_id):
        """Deliver a webhook in a background thread."""
        from flask import current_app
        try:
            app = current_app._get_current_object()
        except RuntimeError:
            # No app context - need to import create_app
            return

        with app.app_context():
            EventService.deliver(delivery_id)

    @staticmethod
    def deliver(delivery_id):
        """Deliver a webhook to the subscription URL."""
        delivery = EventDelivery.query.get(delivery_id)
        if not delivery:
            return

        subscription = delivery.subscription
        if not subscription or not subscription.is_active:
            delivery.status = EventDelivery.STATUS_FAILED
            db.session.commit()
            return

        payload = delivery.get_payload()
        payload_json = json.dumps(payload)
        delivery_uuid = str(uuid.uuid4())

        headers = {
            'Content-Type': 'application/json',
            'X-ServerKit-Event': delivery.event_type,
            'X-ServerKit-Delivery': delivery_uuid,
            'User-Agent': 'ServerKit-Webhooks/1.0',
        }

        # HMAC signature if secret is set
        if subscription.secret:
            signature = hmac.new(
                subscription.secret.encode(),
                payload_json.encode(),
                hashlib.sha256,
            ).hexdigest()
            headers['X-ServerKit-Signature'] = f'sha256={signature}'

        # Add custom headers
        custom_headers = subscription.get_headers()
        if custom_headers:
            headers.update(custom_headers)

        delivery.attempts = (delivery.attempts or 0) + 1
        start_time = time.time()

        try:
            resp = http_requests.post(  # nosec B113
                subscription.url,
                data=payload_json,
                headers=headers,
                timeout=subscription.timeout_seconds or 10,
            )
            elapsed_ms = (time.time() - start_time) * 1000

            delivery.http_status = resp.status_code
            delivery.response_body = resp.text[:1000] if resp.text else None
            delivery.duration_ms = round(elapsed_ms, 2)

            if 200 <= resp.status_code < 300:
                delivery.status = EventDelivery.STATUS_SUCCESS
                delivery.delivered_at = datetime.utcnow()
            else:
                _schedule_retry(delivery, subscription)

        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            delivery.duration_ms = round(elapsed_ms, 2)
            delivery.response_body = str(e)[:1000]
            _schedule_retry(delivery, subscription)

        db.session.commit()

    @staticmethod
    def retry_failed():
        """Retry failed deliveries that are due."""
        now = datetime.utcnow()
        pending = EventDelivery.query.filter(
            EventDelivery.status == EventDelivery.STATUS_PENDING,
            EventDelivery.next_retry_at <= now,
            EventDelivery.attempts > 0,
        ).all()

        for delivery in pending:
            EventService.deliver(delivery.id)

    @staticmethod
    def send_test(subscription_id):
        """Send a test event to a subscription."""
        sub = EventSubscription.query.get(subscription_id)
        if not sub:
            return None

        delivery = EventDelivery(
            subscription_id=sub.id,
            event_type='test.ping',
            status=EventDelivery.STATUS_PENDING,
        )
        delivery.set_payload({
            'event': 'test.ping',
            'timestamp': datetime.utcnow().isoformat(),
            'message': 'This is a test webhook from ServerKit',
        })
        db.session.add(delivery)
        db.session.commit()

        EventService.deliver(delivery.id)
        return delivery

    @staticmethod
    def get_deliveries(subscription_id, page=1, per_page=50):
        """Get delivery history for a subscription."""
        return EventDelivery.query.filter_by(
            subscription_id=subscription_id
        ).order_by(
            EventDelivery.created_at.desc()
        ).paginate(page=page, per_page=per_page, error_out=False)

    @staticmethod
    def cleanup_old_deliveries(days=30):
        """Purge old delivery records."""
        cutoff = datetime.utcnow() - timedelta(days=days)
        deleted = EventDelivery.query.filter(EventDelivery.created_at < cutoff).delete()
        db.session.commit()
        return deleted


def _schedule_retry(delivery, subscription):
    """Schedule a retry with exponential backoff."""
    max_retries = subscription.retry_count or 3
    if delivery.attempts >= max_retries:
        delivery.status = EventDelivery.STATUS_FAILED
    else:
        # Exponential backoff: 10s, 30s, 90s
        delay_seconds = 10 * (3 ** (delivery.attempts - 1))
        delivery.next_retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        delivery.status = EventDelivery.STATUS_PENDING
