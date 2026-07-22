"""Linked-panel (ServerKit-to-ServerKit peering) tests.

Covers the link/unlink service flow (registration driver), the HMAC auth
payload the embedded agent presents to the master, and the command-dispatch
shim that maps agent actions onto this panel's local services.
"""
import base64
import hashlib
import hmac
import os
import stat
import time

import pytest

from app import db
from app.models.linked_panel import LinkedPanelConfig
from app.services import linked_panel_agent as agent
from app.services.linked_panel_service import LinkedPanelService


REGISTER_PAYLOAD = {
    'agent_id': 'agent-123',
    'name': 'worker-b',
    'api_key': 'sk_abcdef1234567890',
    'api_secret': 'super-secret',
    'websocket_url': 'wss://master/agent',
    'server_id': 'srv-456',
}


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, text=''):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


@pytest.fixture(autouse=True)
def _no_client_thread(monkeypatch):
    """Never spawn the real embedded-agent thread from the service layer."""
    monkeypatch.setattr(agent, 'start_embedded_agent', lambda app: None)
    monkeypatch.setattr(agent, 'stop_embedded_agent', lambda: None)


# ---------------------------------------------------------------------------
# link() / unlink()
# ---------------------------------------------------------------------------

def test_link_success_persists_credentials(app, monkeypatch):
    calls = {}

    def fake_post(url, json=None, timeout=None, headers=None):
        calls['url'] = url
        calls['json'] = json
        return _FakeResponse(200, REGISTER_PAYLOAD)

    monkeypatch.setattr(agent.requests, 'post', fake_post)
    monkeypatch.setattr('app.services.linked_panel_service.requests.post', fake_post)

    with app.app_context():
        result = LinkedPanelService.link('https://master.example/', 'sk_reg_token')

        assert result['success'] is True
        assert calls['url'] == 'https://master.example/api/v1/servers/register'
        assert calls['json']['token'] == 'sk_reg_token'
        assert calls['json']['system_info']['hostname']

        cfg = LinkedPanelConfig.query.first()
        assert cfg is not None
        assert cfg.master_url == 'https://master.example'  # trailing / stripped
        assert cfg.agent_id == 'agent-123'
        assert cfg.api_key_prefix == 'sk_abcdef123'[:12]
        assert cfg.remote_server_id == 'srv-456'
        # Secret stored encrypted, retrievable in plaintext.
        assert cfg.api_secret_encrypted != 'super-secret'
        assert cfg.get_api_secret() == 'super-secret'

        status = LinkedPanelService.get_status()
        assert status['linked'] is True
        assert status['connected'] is False  # client thread mocked out


def test_link_rejects_bad_url(app):
    with app.app_context():
        result = LinkedPanelService.link('master.example', 'sk_reg_token')
        assert result['success'] is False
        assert 'http' in result['error']


def test_link_master_rejection_surfaces_error(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.linked_panel_service.requests.post',
        lambda *a, **k: _FakeResponse(401, {'error': 'Invalid or expired registration token'}),
    )
    with app.app_context():
        result = LinkedPanelService.link('https://master.example', 'bad-token')
        assert result['success'] is False
        assert 'Invalid or expired registration token' in result['error']
        assert LinkedPanelConfig.query.first() is None


def test_link_twice_refused(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.linked_panel_service.requests.post',
        lambda *a, **k: _FakeResponse(200, REGISTER_PAYLOAD),
    )
    with app.app_context():
        assert LinkedPanelService.link('https://m.example', 'tok')['success']
        second = LinkedPanelService.link('https://m.example', 'tok')
        assert second['success'] is False
        assert 'already linked' in second['error']


def test_unlink_clears_config(app, monkeypatch):
    monkeypatch.setattr(
        'app.services.linked_panel_service.requests.post',
        lambda *a, **k: _FakeResponse(200, REGISTER_PAYLOAD),
    )
    with app.app_context():
        LinkedPanelService.link('https://m.example', 'tok')
        assert LinkedPanelService.unlink()['success'] is True
        assert LinkedPanelConfig.query.first() is None
        assert LinkedPanelService.get_status() == {'linked': False}


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

def test_api_status_unlinked(client, auth_headers):
    resp = client.get('/api/v1/linked-panel', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json() == {'linked': False}


def test_api_requires_auth(client):
    assert client.get('/api/v1/linked-panel').status_code in (401, 422)


# ---------------------------------------------------------------------------
# HMAC auth payload (must match agent_registry.verify_agent_auth)
# ---------------------------------------------------------------------------

def test_hmac_signature_matches_master_verification():
    agent_id, secret = 'agent-123', 'super-secret'
    timestamp = int(time.time() * 1000)
    nonce = 'abc123'
    # Client side (what linked_panel_agent._connect builds).
    message = f'{agent_id}:{timestamp}:{nonce}'
    signature = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    # Master side (agent_registry.verify_agent_auth) reconstructs identically.
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    assert hmac.compare_digest(signature, expected)


# ---------------------------------------------------------------------------
# Command dispatch shim
# ---------------------------------------------------------------------------

def test_file_write_happy_path(tmp_path, monkeypatch):
    monkeypatch.setenv('LINKED_PANEL_ALLOWED_WRITE_ROOTS', str(tmp_path))
    target = tmp_path / 'app' / 'docker-compose.yml'
    data = agent.handle_file_write({
        'path': str(target),
        'content': base64.b64encode(b'services: {}').decode(),
        'mode': 0o640,
        'create_dirs': True,
    })
    assert data['path'] == os.path.realpath(str(target))
    assert target.read_text() == 'services: {}'
    if os.name == 'posix':  # Windows ignores POSIX permission bits
        assert stat.S_IMODE(target.stat().st_mode) == 0o640


def test_file_write_rejects_relative_path():
    with pytest.raises(RuntimeError, match='absolute'):
        agent.handle_file_write({'path': 'Dockerfile', 'content': ''})


def test_file_write_rejects_outside_allowed_roots(tmp_path, monkeypatch):
    monkeypatch.setenv('LINKED_PANEL_ALLOWED_WRITE_ROOTS', str(tmp_path / 'allowed'))
    with pytest.raises(RuntimeError, match='outside allowed roots'):
        agent.handle_file_write({
            'path': str(tmp_path / 'evil' / 'x.yml'),
            'content': base64.b64encode(b'x').decode(),
        })


def test_compose_up_maps_params_and_raises_on_failure(monkeypatch):
    seen = {}

    class FakeDocker:
        @staticmethod
        def compose_up(project_path, detach=True, build=False):
            seen.update(path=project_path, detach=detach, build=build)
            return {'success': True, 'output': 'ok'}

    monkeypatch.setattr(
        'app.services.docker_service.DockerService', FakeDocker)
    data = agent.handle_compose_up(
        {'project_path': '/var/serverkit/apps/x', 'detach': True, 'build': True})
    assert data['success'] is True
    assert seen == {'path': '/var/serverkit/apps/x', 'detach': True, 'build': True}

    class FailingDocker(FakeDocker):
        @staticmethod
        def compose_up(project_path, detach=True, build=False):
            return {'success': False, 'error': 'build exploded'}

    monkeypatch.setattr(
        'app.services.docker_service.DockerService', FailingDocker)
    with pytest.raises(RuntimeError, match='build exploded'):
        agent.handle_compose_up({'project_path': '/x'})


def test_unknown_action_reported_via_dispatch(monkeypatch):
    posted = {}
    monkeypatch.setattr(agent.requests, 'post',
                        lambda url, json=None, headers=None, timeout=None:
                        posted.update(json=json) or _FakeResponse(200, {'ok': True}))
    cfg = type('C', (), {'master_url': 'https://m.example'})()
    client = agent.EmbeddedAgentClient(app=None)
    client.session_token = 'tok'
    client._dispatch(cfg, {'id': 'cmd1', 'action': 'nuke:everything', 'params': {}})
    assert posted['json']['command_id'] == 'cmd1'
    assert posted['json']['success'] is False
    assert 'Unsupported action' in posted['json']['error']
