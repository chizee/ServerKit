"""CrowdSec API endpoints (serverkit-crowdsec extension).

Mounted under ``/api/v1/crowdsec`` via the manifest's ``url_prefix``. Thin
routing layer over :class:`CrowdSecService` — all cscli work happens in the
service. Reads need viewer, mutations need admin (same split as the core
Fail2ban surface).
"""
from flask import Blueprint, jsonify, request

from app.middleware.rbac import admin_required, viewer_required
from .crowdsec_service import CrowdSecService

crowdsec_bp = Blueprint('crowdsec', __name__)

_NOT_INSTALLED = (
    'CrowdSec is not installed on this host. See the status endpoint for '
    'installation guidance.'
)


def _installed_or_error():
    """Return an error response tuple when CrowdSec is absent, else None."""
    if not CrowdSecService.is_installed():
        return jsonify({'error': _NOT_INSTALLED}), 503
    return None


# ── Status ──

@crowdsec_bp.route('/status', methods=['GET'])
@viewer_required
def get_status():
    """Installed / running / version / LAPI / allowlist-support summary."""
    return jsonify(CrowdSecService.get_status()), 200


# ── Decisions ──

@crowdsec_bp.route('/decisions', methods=['GET'])
@viewer_required
def list_decisions():
    """Active decisions, flattened. Filters: ?ip= &scope= &type=."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = CrowdSecService.list_decisions(
        ip=request.args.get('ip'),
        scope=request.args.get('scope'),
        dtype=request.args.get('type'),
    )
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to list decisions')}), 500
    return jsonify({'decisions': result['decisions']}), 200


@crowdsec_bp.route('/decisions', methods=['POST'])
@admin_required
def add_decision():
    """Ban an IP or range: {ip, duration?, reason?, type?}."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json() or {}
    ip = (data.get('ip') or '').strip()
    if not ip:
        return jsonify({'error': 'ip is required'}), 400
    result = CrowdSecService.add_decision(
        ip,
        duration=data.get('duration') or '4h',
        reason=data.get('reason') or 'Manual ban from ServerKit',
        dtype=data.get('type') or 'ban',
    )
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to add decision')}), 400
    return jsonify(result), 201


@crowdsec_bp.route('/decisions/<path:ip>', methods=['DELETE'])
@admin_required
def delete_decision(ip):
    """Remove all decisions for an IP (path converter allows CIDR ranges)."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = CrowdSecService.delete_decision(ip)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to delete decision')}), 400
    return jsonify(result), 200


# ── Alerts ──

@crowdsec_bp.route('/alerts', methods=['GET'])
@viewer_required
def list_alerts():
    """Recent alerts (?limit=, default 50)."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = CrowdSecService.list_alerts(limit=request.args.get('limit', 50))
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to list alerts')}), 500
    return jsonify({'alerts': result['alerts']}), 200


# ── Allowlists (feature-detected) ──

@crowdsec_bp.route('/allowlists', methods=['GET'])
@viewer_required
def list_allowlists():
    """Allowlists, or {supported: false} when the cscli lacks the subcommand."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = CrowdSecService.list_allowlists()
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to list allowlists')}), 500
    return jsonify({
        'supported': result.get('supported', False),
        'allowlists': result.get('allowlists', []),
        'message': result.get('message'),
    }), 200


@crowdsec_bp.route('/allowlists', methods=['POST'])
@admin_required
def create_allowlist():
    """Create an allowlist: {name, description?}."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    result = CrowdSecService.create_allowlist(name, data.get('description') or '')
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to create allowlist')}), 400
    return jsonify(result), 201


@crowdsec_bp.route('/allowlists/<name>', methods=['GET'])
@viewer_required
def inspect_allowlist(name):
    """Allowlist detail (items) via cscli allowlists inspect."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = CrowdSecService.inspect_allowlist(name)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to inspect allowlist')}), 400
    return jsonify({'allowlist': result.get('allowlist')}), 200


@crowdsec_bp.route('/allowlists/<name>/items', methods=['POST'])
@admin_required
def add_allowlist_item(name):
    """Add an entry: {value, expiration?, comment?}."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json() or {}
    value = (data.get('value') or '').strip()
    if not value:
        return jsonify({'error': 'value is required'}), 400
    result = CrowdSecService.add_allowlist_entry(
        name, value,
        expiration=data.get('expiration'),
        comment=data.get('comment'),
    )
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to add allowlist entry')}), 400
    return jsonify(result), 201


@crowdsec_bp.route('/allowlists/<name>/items', methods=['DELETE'])
@admin_required
def remove_allowlist_item(name):
    """Remove an entry — value via ?value= or JSON body (CIDRs carry a '/')."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    value = (request.args.get('value') or data.get('value') or '').strip()
    if not value:
        return jsonify({'error': 'value is required'}), 400
    result = CrowdSecService.remove_allowlist_entry(name, value)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to remove allowlist entry')}), 400
    return jsonify(result), 200


# ── Metrics ──

@crowdsec_bp.route('/metrics', methods=['GET'])
@viewer_required
def get_metrics():
    """Raw engine metrics, best-effort (shape varies across versions)."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = CrowdSecService.get_metrics()
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to fetch metrics')}), 500
    return jsonify({'metrics': result.get('metrics')}), 200
