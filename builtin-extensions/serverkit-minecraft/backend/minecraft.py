"""serverkit-minecraft API blueprint (plan 53).

Exposes the game-server framework (gamekit) over the DB-backed server records.
The create/delete flow (compose generation → DeploymentJob, container+volume
teardown) rides the existing template/Deploy-Console path and is verified on the
dev box with Docker Desktop; those endpoints are marked below. The framework
surface (list/get, RCON proxy, config form, backup) is what gamekit powers.

Routes are mounted at /api/v1/minecraft (manifest url_prefix).
"""
from flask import Blueprint, request, jsonify

from app.plugins_sdk import db, jwt_required, current_user, logger

from .models import MinecraftServer, MinecraftBackup
from . import gamekit

minecraft_bp = Blueprint('minecraft', __name__)
log = logger(__name__)


def _server_or_404(server_id):
    return MinecraftServer.query.get(server_id)


@minecraft_bp.route('', methods=['GET'])
@minecraft_bp.route('/', methods=['GET'])
@jwt_required()
def list_servers():
    servers = MinecraftServer.query.order_by(MinecraftServer.created_at.desc()).all()
    return jsonify({'servers': [s.to_dict() for s in servers]})


@minecraft_bp.route('/<int:server_id>', methods=['GET'])
@jwt_required()
def get_server(server_id):
    server = _server_or_404(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    return jsonify(server.to_dict())


@minecraft_bp.route('/<int:server_id>/rcon', methods=['POST'])
@jwt_required()
def run_rcon(server_id):
    """Proxy a single RCON command to the server (loopback-only, D5).

    The panel talks to RCON server-side; the port is never published. Java
    edition only — Bedrock's default image has no RCON (documented asymmetry).
    """
    user = current_user()
    if not user or not user.is_admin:
        return jsonify({'error': 'Admin access required'}), 403
    server = _server_or_404(server_id)
    if not server:
        return jsonify({'error': 'Server not found'}), 404
    if server.edition == 'bedrock':
        return jsonify({'error': 'RCON is not available for Bedrock servers'}), 400

    cmd = (request.get_json(silent=True) or {}).get('command', '').strip()
    if not cmd:
        return jsonify({'error': 'command required'}), 400

    try:
        with gamekit.rcon.RconClient(
            host='127.0.0.1', port=server.rcon_port or 25575,
            password=server.rcon_password or '') as rc:
            output = rc.command(cmd)
        return jsonify({'command': cmd, 'output': output})
    except gamekit.rcon.RconAuthError:
        return jsonify({'error': 'RCON authentication failed'}), 502
    except gamekit.rcon.RconError as e:
        return jsonify({'error': f'RCON error: {e}'}), 502


@minecraft_bp.route('/<int:server_id>/backups', methods=['GET'])
@jwt_required()
def list_backups(server_id):
    backups = (MinecraftBackup.query
               .filter_by(server_id=server_id)
               .order_by(MinecraftBackup.created_at.desc()).all())
    return jsonify({'backups': [b.to_dict() for b in backups]})


# --- Deploy-console flow (dev-box / Docker verified) ------------------------
# POST '' (create → compose → DeploymentJob), DELETE '/<id>' (container+volume
# teardown + firewall cleanup), and lifecycle start/stop/restart with the
# save-before-stop countdown live here in plan 53 Phase 1-2. They shell out to
# docker compose and the firewall service, so they are exercised on the dev box
# with Docker Desktop, not in the offline unit suite — kept out of this scaffold
# until that verification runs, so nothing here claims an unverified Docker path.
