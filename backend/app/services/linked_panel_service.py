"""Linked-panel management: link/unlink/status for ServerKit-to-ServerKit peering.

Linking = register this panel as an agent on the master (single REST call
with the master's registration token), persist the returned credentials,
and start the embedded agent client (app/services/linked_panel_agent.py).
"""
import logging
from datetime import datetime
from typing import Dict

import requests

from app import db
from app.models.linked_panel import LinkedPanelConfig
from app.services import linked_panel_agent
from app.services.linked_panel_agent import AGENT_VERSION, collect_system_info

logger = logging.getLogger(__name__)

REGISTER_TIMEOUT_S = 20


class LinkedPanelService:
    """Manages this panel's link to a master ServerKit panel."""

    @classmethod
    def get_status(cls) -> Dict:
        cfg = LinkedPanelConfig.query.first()
        if not cfg:
            return {'linked': False}
        status = cfg.to_dict()
        client = linked_panel_agent.get_client()
        status['connected'] = bool(client and client.session_token)
        status['last_error'] = client.last_error if client else None
        status['connected_at'] = (
            datetime.utcfromtimestamp(client.connected_at).isoformat()
            if client and client.connected_at else None
        )
        status['last_heartbeat_at'] = (
            datetime.utcfromtimestamp(client.last_heartbeat_at).isoformat()
            if client and client.last_heartbeat_at else None
        )
        return status

    @classmethod
    def link(cls, master_url: str, registration_token: str, name: str = None) -> Dict:
        """Register with the master and start the embedded agent.

        The token comes from the master's Servers page (Add Server /
        regenerate-token) — the same ``sk_reg_…`` token the Go agent's
        install script consumes.
        """
        master_url = (master_url or '').strip().rstrip('/')
        registration_token = (registration_token or '').strip()
        if not master_url.startswith(('http://', 'https://')):
            return {'success': False, 'error': 'master_url must start with http:// or https://'}
        if not registration_token:
            return {'success': False, 'error': 'registration_token is required'}

        if LinkedPanelConfig.query.first():
            return {'success': False, 'error': 'This panel is already linked — unlink first'}

        # One-shot registration on the master: exchanges the single-use
        # token for scoped agent credentials (same endpoint the Go agent
        # install script calls).
        try:
            resp = requests.post(
                f'{master_url}/api/v1/servers/register',
                json={
                    'token': registration_token,
                    'name': name,
                    'system_info': collect_system_info(),
                    'agent_version': AGENT_VERSION,
                },
                timeout=REGISTER_TIMEOUT_S,
            )
        except requests.RequestException as exc:
            return {'success': False, 'error': f'Cannot reach master panel: {exc}'}

        if resp.status_code != 200:
            try:
                error = resp.json().get('error')
            except ValueError:
                error = resp.text[:200]
            return {'success': False,
                    'error': f'Master rejected registration ({resp.status_code}): {error}'}

        data = resp.json()
        required = ('agent_id', 'api_key', 'api_secret', 'server_id')
        if not all(data.get(k) for k in required):
            return {'success': False, 'error': f'Unexpected registration response: {data!r}'}

        cfg = LinkedPanelConfig(
            master_url=master_url,
            agent_id=data['agent_id'],
            api_key_prefix=data['api_key'][:12],
            remote_server_id=data['server_id'],
            remote_server_name=data.get('name'),
            enabled=True,
        )
        cfg.set_api_secret(data['api_secret'])
        db.session.add(cfg)
        db.session.commit()

        # (Re)start the embedded agent against the fresh credentials.
        linked_panel_agent.stop_embedded_agent()
        from flask import current_app
        linked_panel_agent.start_embedded_agent(current_app._get_current_object())

        logger.info('Linked to master panel %s as server %s',
                    master_url, cfg.remote_server_id)
        return {'success': True, 'status': cls.get_status()}

    @classmethod
    def unlink(cls) -> Dict:
        linked_panel_agent.stop_embedded_agent()
        cfg = LinkedPanelConfig.query.first()
        if cfg:
            db.session.delete(cfg)
            db.session.commit()
        return {'success': True}

    @classmethod
    def start_client_if_linked(cls, app):
        """App-startup hook: resume the embedded agent for a persisted link."""
        try:
            if LinkedPanelConfig.query.first():
                linked_panel_agent.start_embedded_agent(app)
        except Exception as exc:  # never block boot on the link
            logger.warning('Could not resume linked-panel agent: %s', exc)
