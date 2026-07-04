"""Small tools blueprint for .htaccess conversion.

Kept out of apps.py on purpose (separate ownership); intended registration:

    from app.api.htaccess_tools import htaccess_tools_bp
    app.register_blueprint(htaccess_tools_bp, url_prefix='/api/v1/apps')

which exposes POST /api/v1/apps/htaccess-convert.
"""
from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

from app.services.htaccess_converter import MAX_INPUT_BYTES, convert

htaccess_tools_bp = Blueprint('htaccess_tools', __name__)


@htaccess_tools_bp.route('/htaccess-convert', methods=['POST'])
@jwt_required()
def htaccess_convert():
    """Convert pasted .htaccess text to nginx directives.

    Pure text transform (no server state touched), so any authenticated
    user may call it. Body: {'htaccess': '<text>'}.
    """
    data = request.get_json(silent=True) or {}
    text = data.get('htaccess')
    if not isinstance(text, str) or not text.strip():
        return jsonify({'error': 'htaccess text is required'}), 400
    if len(text.encode('utf-8', errors='replace')) > MAX_INPUT_BYTES:
        return jsonify({'error': '.htaccess input exceeds the 256KB limit'}), 413
    try:
        return jsonify(convert(text))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
