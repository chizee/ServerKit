"""Declarative serverkit.yaml manifest API.

Phase 0: `scaffold` (render a v1 manifest from a live app).
Later phases add `get`, `plan` and `apply`. Admin-gated; applies are
audit-logged.
"""

from flask import Blueprint, jsonify, request, Response
from flask_jwt_extended import jwt_required, get_jwt_identity

from app.models.application import Application
from app.models.user import User
from app.services.manifest_scaffold_service import ManifestScaffoldService
from app.services.manifest_spec_service import ManifestSpecService, ManifestError

manifests_bp = Blueprint('manifests', __name__)


def _require_admin():
    user = User.query.get(get_jwt_identity())
    if not user or user.role != 'admin':
        return None, (jsonify({'error': 'Admin access required'}), 403)
    return user, None


@manifests_bp.route('/scaffold', methods=['GET'])
@jwt_required()
def scaffold_manifest():
    """GET /api/v1/manifests/scaffold?app_id=&format=json|yaml"""
    user, err = _require_admin()
    if err:
        return err

    app_id = request.args.get('app_id', type=int)
    if not app_id:
        return jsonify({'error': 'app_id is required'}), 400

    app = Application.query.get(app_id)
    if not app:
        return jsonify({'error': 'Application not found'}), 404

    fmt = (request.args.get('format') or 'json').lower()
    if fmt == 'yaml':
        yaml_text = ManifestScaffoldService.scaffold_yaml(app)
        return Response(yaml_text, mimetype='text/yaml')

    manifest = ManifestScaffoldService.scaffold_for_app(app)
    return jsonify({'manifest': manifest,
                    'yaml': ManifestScaffoldService.scaffold_yaml(app)}), 200


@manifests_bp.route('/validate', methods=['POST'])
@jwt_required()
def validate_manifest():
    """POST /api/v1/manifests/validate  { content | manifest } -> normalized summary."""
    user, err = _require_admin()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    try:
        if 'content' in data:
            normalized = ManifestSpecService.normalize_text(data['content'])
        elif 'manifest' in data:
            normalized = ManifestSpecService.normalize(data['manifest'])
        else:
            return jsonify({'error': 'Provide `content` or `manifest`'}), 400
    except ManifestError as exc:
        return jsonify({'valid': False, 'errors': exc.errors}), 200

    return jsonify({
        'valid': True,
        'summary': ManifestSpecService.summarize(normalized),
        'normalized': normalized,
    }), 200
