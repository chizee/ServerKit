"""Unified connection registry — one normalized, read-only list of every
external account ServerKit is connected to (source, DNS, infra, registrar,
storage). The individual write paths still live in their own blueprints; this
is the single source of truth for "what's connected".
"""

from flask import Blueprint, jsonify

from app.middleware.rbac import admin_required, get_current_user
from app.services.connection_registry import ConnectionRegistry

connections_bp = Blueprint('connections', __name__)


@connections_bp.route('', methods=['GET'])
@connections_bp.route('/', methods=['GET'])
@admin_required
def list_connections():
    """List every connected external account (secret-free). Admin-only — these are
    server-wide credentials (Cloudflare tokens, cloud keys, …), not personal
    settings, so the whole Connections surface lives under Administration."""
    user = get_current_user()
    return jsonify({'connections': ConnectionRegistry.list_all(
        user_id=user.id if user else None)})
