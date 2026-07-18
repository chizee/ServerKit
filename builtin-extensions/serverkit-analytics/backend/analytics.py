"""Web Analytics API endpoints (serverkit-analytics extension).

Mounted under ``/api/v1/analytics`` via the manifest ``url_prefix``. Thin
routing layer over the extension services:

* ``ingest_service``      — validation, bot filter, visitor hashing, buffer+flush
* ``report_service``      — rollup-backed dashboard queries
* ``log_ingest_service``  — access-log parsing (apache/nginx combined)
* ``wp_integration`` / ``nginx_integration`` — one-click tracker injection

Auth split mirrors serverkit-tramo / serverkit-k8s: report reads need viewer,
site mutations need admin. The TWO exceptions are the tracker surface — the
public ``POST /collect`` and ``GET /tracker.js`` — which carry NO JWT because a
tracked site's visitors have none. They authenticate per-site via the site_key
(not a JWT) and are protected by rate limiting, a body-size cap, and bot
filtering. The plugin-disabled 503 guard (attached by plugin_service) still runs
on every route, so disabling the extension stops collection for free.
"""
import logging

from flask import Blueprint, jsonify

logger = logging.getLogger(__name__)

analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.route('/ping', methods=['GET'])
def ping():
    """Unauthenticated liveness probe (also proves the 503 status guard)."""
    return jsonify({'ok': True, 'plugin': 'serverkit-analytics'}), 200
