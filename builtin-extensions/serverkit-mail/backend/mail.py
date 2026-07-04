"""Mail Server API endpoints (serverkit-mail extension).

Mounted under ``/api/v1/mail`` via the manifest's ``url_prefix``. Thin routing
layer over the extension services — all Docker, Stalwart-API, DNS, and DKIM work
happens in the services. Reads need viewer, mutations need admin (same split as
the serverkit-dns-server extension).

``_installed_or_error`` guards only the routes that genuinely need a running
Stalwart engine (``/queue``, ``/service/<action>``). Domain/mailbox/forwarder
CRUD writes to *our* DB and reconciles to Stalwart best-effort, so it works even
before the engine is installed (operators can stage config first).
"""
from flask import Blueprint, jsonify, request

from app.middleware.rbac import admin_required, viewer_required

from .mail_service import MailService
from .stalwart_service import StalwartService
from .preflight_service import PreflightService
from .dns_mail_service import DkimDnsService

mail_bp = Blueprint('mail', __name__)

_NOT_INSTALLED = (
    'The mail server is not installed. Install it from the Mail Server page '
    '(admin only).'
)


def _installed_or_error():
    """Return an error response tuple when the engine is absent, else None."""
    if not StalwartService.is_installed():
        return jsonify({'error': _NOT_INSTALLED}), 503
    return None


def _server_ip(data=None):
    """Resolve the server public IP: explicit body value, else system settings."""
    if data and data.get('server_ip'):
        return str(data['server_ip']).strip()
    try:
        from app.services.site_domain_service import SiteDomainService
        return SiteDomainService.server_ip()
    except Exception:  # noqa: BLE001
        return None


def _domain_or_404(domain_id):
    from .models import MailDomain
    return MailDomain.query.get(domain_id)


# ── Status / lifecycle ──

@mail_bp.route('/status', methods=['GET'])
@viewer_required
def get_status():
    """Engine status + latest deliverability preflight."""
    return jsonify(MailService.get_status()), 200


@mail_bp.route('/install', methods=['POST'])
@admin_required
def install():
    """Start the Stalwart container: {hostname}."""
    data = request.get_json() or {}
    hostname = (data.get('hostname') or '').strip()
    if not hostname:
        return jsonify({'error': 'hostname is required'}), 400
    result = StalwartService.install(hostname)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Install failed')}), 400
    return jsonify(result), 201


@mail_bp.route('/install', methods=['DELETE'])
@admin_required
def uninstall():
    """Remove the container (?keep_data=true keeps the mail data)."""
    keep_data = (request.args.get('keep_data', 'true').lower()
                 not in ('false', '0', 'no'))
    result = StalwartService.uninstall(keep_data=keep_data)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Uninstall failed')}), 400
    return jsonify(result), 200


@mail_bp.route('/service/<action>', methods=['POST'])
@admin_required
def control_service(action):
    """Start / stop / restart the engine container."""
    guard = _installed_or_error()
    if guard:
        return guard
    if action not in ('start', 'stop', 'restart'):
        return jsonify({'error': "action must be start, stop or restart"}), 400
    result = StalwartService.control(action)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Service control failed')}), 400
    return jsonify(result), 200


# ── Preflight ──

@mail_bp.route('/preflight', methods=['GET'])
@viewer_required
def get_preflight():
    """Latest persisted preflight result (or null)."""
    return jsonify({'preflight': PreflightService.latest()}), 200


@mail_bp.route('/preflight', methods=['POST'])
@admin_required
def run_preflight():
    """Run and persist a deliverability preflight: {hostname, server_ip?}."""
    data = request.get_json() or {}
    hostname = (data.get('hostname') or '').strip()
    if not hostname:
        return jsonify({'error': 'hostname is required'}), 400
    server_ip = _server_ip(data)
    result = PreflightService.run(hostname, server_ip=server_ip)
    return jsonify(result), 200


# ── Domains ──

@mail_bp.route('/domains', methods=['GET'])
@viewer_required
def list_domains():
    return jsonify({'domains': MailService.list_domains()}), 200


@mail_bp.route('/domains', methods=['POST'])
@admin_required
def add_domain():
    """Add a mail domain: {name, catch_all_target?}."""
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    result = MailService.add_domain(name, catch_all_target=data.get('catch_all_target'))
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to add domain')}), 400
    return jsonify(result), 201


@mail_bp.route('/domains/<int:domain_id>', methods=['GET'])
@viewer_required
def get_domain(domain_id):
    domain = MailService.get_domain(domain_id)
    if not domain:
        return jsonify({'error': 'Domain not found'}), 404
    return jsonify(domain), 200


@mail_bp.route('/domains/<int:domain_id>', methods=['PATCH'])
@admin_required
def update_domain(domain_id):
    """Update a domain: {is_active?, catch_all_target?}. Activation is gated on a
    passing preflight (or ?force=true)."""
    data = request.get_json() or {}
    force = (request.args.get('force', 'false').lower() in ('true', '1', 'yes')) \
        or bool(data.get('force'))
    is_active = data.get('is_active')
    if is_active is not None:
        result = MailService.set_domain_active(domain_id, bool(is_active), force=force)
    else:
        result = MailService.update_domain(
            domain_id, catch_all_target=data.get('catch_all_target'))
    if not result.get('success'):
        code = 409 if result.get('code') == 'preflight_required' else 400
        return jsonify({'error': result.get('error', 'Update failed'),
                        'preflight': result.get('preflight')}), code
    return jsonify(result), 200


@mail_bp.route('/domains/<int:domain_id>', methods=['DELETE'])
@admin_required
def remove_domain(domain_id):
    result = MailService.remove_domain(domain_id)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to remove domain')}), 400
    return jsonify(result), 200


# ── DKIM / DNS / cert ──

@mail_bp.route('/domains/<int:domain_id>/dkim', methods=['POST'])
@admin_required
def generate_dkim(domain_id):
    domain = _domain_or_404(domain_id)
    if not domain:
        return jsonify({'error': 'Domain not found'}), 404
    result = DkimDnsService.generate_dkim(domain)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'DKIM generation failed')}), 400
    return jsonify(result), 200


@mail_bp.route('/domains/<int:domain_id>/dns', methods=['GET'])
@viewer_required
def dns_instructions(domain_id):
    domain = _domain_or_404(domain_id)
    if not domain:
        return jsonify({'error': 'Domain not found'}), 404
    return jsonify(DkimDnsService.dns_instructions(domain, server_ip=_server_ip())), 200


@mail_bp.route('/domains/<int:domain_id>/dns/deploy', methods=['POST'])
@admin_required
def deploy_dns(domain_id):
    domain = _domain_or_404(domain_id)
    if not domain:
        return jsonify({'error': 'Domain not found'}), 404
    data = request.get_json(silent=True) or {}
    result = DkimDnsService.deploy_dns(domain_id, server_ip=_server_ip(data))
    # A manual-instructions outcome is still a 200 (there's nothing to fix).
    if not result.get('success') and not result.get('manual'):
        return jsonify(result), 400
    return jsonify(result), 200


@mail_bp.route('/domains/<int:domain_id>/cert', methods=['POST'])
@admin_required
def request_cert(domain_id):
    domain = _domain_or_404(domain_id)
    if not domain:
        return jsonify({'error': 'Domain not found'}), 404
    result = DkimDnsService.request_cert(f'mail.{domain.name}')
    if not result.get('success'):
        return jsonify(result), 200 if result.get('skipped') else 400
    return jsonify(result), 200


# ── Mailboxes ──

@mail_bp.route('/domains/<int:domain_id>/mailboxes', methods=['GET'])
@viewer_required
def list_mailboxes(domain_id):
    if not _domain_or_404(domain_id):
        return jsonify({'error': 'Domain not found'}), 404
    return jsonify({'mailboxes': MailService.list_mailboxes(domain_id)}), 200


@mail_bp.route('/domains/<int:domain_id>/mailboxes', methods=['POST'])
@admin_required
def add_mailbox(domain_id):
    """Create a mailbox: {local_part, password, quota_mb?, display_name?}."""
    data = request.get_json() or {}
    local_part = (data.get('local_part') or '').strip()
    password = data.get('password')
    if not local_part:
        return jsonify({'error': 'local_part is required'}), 400
    if not password:
        return jsonify({'error': 'password is required'}), 400
    result = MailService.add_mailbox(
        domain_id, local_part, password,
        quota_mb=data.get('quota_mb', 0),
        display_name=data.get('display_name'))
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to create mailbox')}), 400
    return jsonify(result), 201


@mail_bp.route('/mailboxes/<int:mailbox_id>', methods=['PATCH'])
@admin_required
def update_mailbox(mailbox_id):
    """Update a mailbox: {quota_mb?, is_active?, display_name?}."""
    data = request.get_json() or {}
    result = MailService.update_mailbox(
        mailbox_id,
        quota_mb=data.get('quota_mb'),
        is_active=data.get('is_active'),
        display_name=data.get('display_name'))
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to update mailbox')}), 400
    return jsonify(result), 200


@mail_bp.route('/mailboxes/<int:mailbox_id>/password', methods=['POST'])
@admin_required
def set_mailbox_password(mailbox_id):
    """Set a mailbox password: {password}."""
    data = request.get_json() or {}
    password = data.get('password')
    if not password:
        return jsonify({'error': 'password is required'}), 400
    result = MailService.set_mailbox_password(mailbox_id, password)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to set password')}), 400
    return jsonify(result), 200


@mail_bp.route('/mailboxes/<int:mailbox_id>', methods=['DELETE'])
@admin_required
def remove_mailbox(mailbox_id):
    result = MailService.remove_mailbox(mailbox_id)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to remove mailbox')}), 400
    return jsonify(result), 200


# ── Autoresponder ──

@mail_bp.route('/mailboxes/<int:mailbox_id>/autoresponder', methods=['GET'])
@viewer_required
def get_autoresponder(mailbox_id):
    result = MailService.get_autoresponder(mailbox_id)
    if result is None:
        return jsonify({'error': 'Mailbox not found'}), 404
    return jsonify({'autoresponder': result}), 200


@mail_bp.route('/mailboxes/<int:mailbox_id>/autoresponder', methods=['PUT'])
@admin_required
def set_autoresponder(mailbox_id):
    """Set the autoresponder: {enabled, subject, body, start_at?, end_at?}."""
    data = request.get_json() or {}
    result = MailService.set_autoresponder(
        mailbox_id,
        enabled=data.get('enabled'),
        subject=data.get('subject'),
        body=data.get('body'),
        start_at=data.get('start_at'),
        end_at=data.get('end_at'))
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to save autoresponder')}), 400
    return jsonify(result), 200


# ── Forwarders ──

@mail_bp.route('/domains/<int:domain_id>/forwarders', methods=['GET'])
@viewer_required
def list_forwarders(domain_id):
    if not _domain_or_404(domain_id):
        return jsonify({'error': 'Domain not found'}), 404
    return jsonify({'forwarders': MailService.list_forwarders(domain_id)}), 200


@mail_bp.route('/domains/<int:domain_id>/forwarders', methods=['POST'])
@admin_required
def add_forwarder(domain_id):
    """Create a forwarder: {source_local_part, destination, keep_copy?}."""
    data = request.get_json() or {}
    source = (data.get('source_local_part') or '').strip()
    destination = (data.get('destination') or '').strip()
    if not source:
        return jsonify({'error': 'source_local_part is required'}), 400
    if not destination:
        return jsonify({'error': 'destination is required'}), 400
    result = MailService.add_forwarder(
        domain_id, source, destination, keep_copy=bool(data.get('keep_copy')))
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to create forwarder')}), 400
    return jsonify(result), 201


@mail_bp.route('/forwarders/<int:forwarder_id>', methods=['DELETE'])
@admin_required
def remove_forwarder(forwarder_id):
    result = MailService.remove_forwarder(forwarder_id)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to remove forwarder')}), 400
    return jsonify(result), 200


# ── Queue ──

@mail_bp.route('/queue', methods=['GET'])
@viewer_required
def get_queue():
    """Outbound queue messages from the Stalwart admin API (best-effort)."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = StalwartService.list_queue()
    return jsonify({'messages': result.get('messages', []),
                    'note': result.get('note')}), 200


@mail_bp.route('/queue/flush', methods=['POST'])
@admin_required
def flush_queue():
    """Ask Stalwart to retry/flush the outbound queue (best-effort)."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = StalwartService.flush_queue()
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Queue flush failed')}), 400
    return jsonify(result), 200
