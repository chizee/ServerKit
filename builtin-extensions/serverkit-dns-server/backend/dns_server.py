"""DNS Server API endpoints (serverkit-dns-server extension).

Mounted under ``/api/v1/dns-server`` via the manifest's ``url_prefix``. Thin
routing layer over :class:`DnsServerService` — all Docker and PowerDNS API
work happens in the service. Reads need viewer, mutations need admin (same
split as the serverkit-crowdsec extension).
"""
from flask import Blueprint, jsonify, request

from app.middleware.rbac import admin_required, viewer_required
from .dns_server_service import DnsServerService

dns_server_bp = Blueprint('dns_server', __name__)

_NOT_INSTALLED = (
    'The DNS server is not installed. Install it from the DNS Server page '
    '(admin only).'
)


def _installed_or_error():
    """Return an error response tuple when the container is absent, else None."""
    if not DnsServerService.is_installed():
        return jsonify({'error': _NOT_INSTALLED}), 503
    return None


# ── Status / lifecycle ──

@dns_server_bp.route('/status', methods=['GET'])
@viewer_required
def get_status():
    """Installed / running / version / nameserver hostname summary."""
    return jsonify(DnsServerService.get_status()), 200


@dns_server_bp.route('/install', methods=['POST'])
@admin_required
def install():
    """Run the PowerDNS container: {ns_hostname, admin_email}."""
    data = request.get_json() or {}
    ns_hostname = (data.get('ns_hostname') or '').strip()
    admin_email = (data.get('admin_email') or '').strip()
    if not ns_hostname:
        return jsonify({'error': 'ns_hostname is required'}), 400
    if not admin_email:
        return jsonify({'error': 'admin_email is required'}), 400
    result = DnsServerService.install(ns_hostname, admin_email)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Install failed')}), 400
    return jsonify(result), 201


@dns_server_bp.route('/install', methods=['DELETE'])
@admin_required
def uninstall():
    """Remove the container (?keep_data=true keeps the SQLite zone data)."""
    keep_data = (request.args.get('keep_data', 'true').lower()
                 not in ('false', '0', 'no'))
    result = DnsServerService.uninstall(keep_data=keep_data)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Uninstall failed')}), 400
    return jsonify(result), 200


# ── Zones ──

@dns_server_bp.route('/zones', methods=['GET'])
@viewer_required
def list_zones():
    guard = _installed_or_error()
    if guard:
        return guard
    result = DnsServerService.list_zones()
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to list zones')}), 500
    return jsonify({'zones': result['zones']}), 200


@dns_server_bp.route('/zones', methods=['POST'])
@admin_required
def create_zone():
    """Create a zone: {name}. SOA/NS are bootstrapped from install params."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'name is required'}), 400
    result = DnsServerService.create_zone(name)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to create zone')}), 400
    return jsonify(result), 201


@dns_server_bp.route('/zones/<path:zone>', methods=['GET'])
@viewer_required
def get_zone(zone):
    """Zone detail: rrsets + DNSSEC status (+DS) + delegation check."""
    guard = _installed_or_error()
    if guard:
        return guard
    result = DnsServerService.get_zone(zone)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to load zone')}), 404
    payload = {'zone': result['zone']}
    if result['zone'].get('dnssec'):
        ds = DnsServerService.get_ds_records(zone)
        payload['ds_records'] = ds.get('ds_records', []) if ds.get('success') else []
    payload['delegation'] = DnsServerService.check_delegation(zone)
    return jsonify(payload), 200


@dns_server_bp.route('/zones/<path:zone>', methods=['DELETE'])
@admin_required
def delete_zone(zone):
    guard = _installed_or_error()
    if guard:
        return guard
    result = DnsServerService.delete_zone(zone)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to delete zone')}), 400
    return jsonify(result), 200


# ── Record sets ──

@dns_server_bp.route('/zones/<path:zone>/rrsets', methods=['POST'])
@admin_required
def upsert_rrset(zone):
    """Create or replace a record set: {name, type, ttl, records: [...]}."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json() or {}
    rtype = (data.get('type') or '').strip()
    if not rtype:
        return jsonify({'error': 'type is required'}), 400
    result = DnsServerService.upsert_rrset(
        zone,
        data.get('name'),
        rtype,
        data.get('ttl', 3600),
        data.get('records') or [],
    )
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to save record set')}), 400
    return jsonify(result), 200


@dns_server_bp.route('/zones/<path:zone>/rrsets', methods=['DELETE'])
@admin_required
def delete_rrset(zone):
    """Delete a record set — name/type via query params or JSON body."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json(silent=True) or {}
    name = request.args.get('name', data.get('name'))
    rtype = (request.args.get('type') or data.get('type') or '').strip()
    if not rtype:
        return jsonify({'error': 'type is required'}), 400
    result = DnsServerService.delete_rrset(zone, name, rtype)
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to delete record set')}), 400
    return jsonify(result), 200


# ── DNSSEC ──

@dns_server_bp.route('/zones/<path:zone>/dnssec', methods=['POST'])
@admin_required
def set_dnssec(zone):
    """Enable/disable DNSSEC: {action: 'enable'|'disable'}. Enable returns
    the DS records to publish at the registrar."""
    guard = _installed_or_error()
    if guard:
        return guard
    data = request.get_json() or {}
    action = (data.get('action') or '').strip().lower()
    if action not in ('enable', 'disable'):
        return jsonify({'error': "action must be 'enable' or 'disable'"}), 400
    result = DnsServerService.set_dnssec(zone, action == 'enable')
    if not result.get('success'):
        return jsonify({'error': result.get('error', 'Failed to update DNSSEC')}), 400
    return jsonify(result), 200
