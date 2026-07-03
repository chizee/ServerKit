"""serverkit-crowdsec extension tests (Panel Improvements #17).

Covers: manifest validity, cscli JSON parsing (decisions/alerts/status),
argv construction for mutations (subprocess stubbed), allowlist feature
detection + fallback, the not-installed path, and blueprint auth/happy
paths with the service stubbed.

The extension backend is loaded exactly the way production loads builtins:
``plugin_service._ensure_builtin_backend_importable`` registers
``builtin-extensions/serverkit-crowdsec/backend`` as ``app.plugins.serverkit-crowdsec``.
"""
import importlib
import json
import os
from types import SimpleNamespace

import pytest

from app.services import plugin_service

SLUG = 'serverkit-crowdsec'
EXT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'builtin-extensions', SLUG,
)


def _load_ext():
    assert plugin_service._ensure_builtin_backend_importable(SLUG), (
        f'builtin extension backend not importable from {EXT_DIR}')
    svc_mod = importlib.import_module(f'app.plugins.{SLUG}.crowdsec_service')
    bp_mod = importlib.import_module(f'app.plugins.{SLUG}.crowdsec')
    return svc_mod, bp_mod


svc_mod, bp_mod = _load_ext()
CrowdSecService = svc_mod.CrowdSecService


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

DECISIONS_JSON = json.dumps([
    {
        'id': 1,
        'scenario': 'crowdsecurity/ssh-bf',
        'created_at': '2026-07-01T10:00:00Z',
        'events_count': 6,
        'source': {
            'ip': '203.0.113.7', 'scope': 'Ip', 'value': '203.0.113.7',
            'cn': 'US', 'as_name': 'ExampleNet',
        },
        'decisions': [
            {
                'id': 42, 'origin': 'crowdsec', 'type': 'ban', 'scope': 'Ip',
                'value': '203.0.113.7', 'duration': '3h59m',
                'scenario': 'crowdsecurity/ssh-bf',
            },
            {
                'id': 43, 'origin': 'cscli', 'type': 'captcha', 'scope': 'Ip',
                'value': '203.0.113.7', 'duration': '1h',
                'scenario': 'manual',
            },
        ],
    },
])

ALERTS_JSON = json.dumps([
    {
        'id': 7,
        'scenario': 'crowdsecurity/http-probing',
        'created_at': '2026-07-02T08:30:00Z',
        'events_count': 11,
        'source': {'ip': '198.51.100.3', 'value': '198.51.100.3', 'cn': 'DE'},
        'decisions': [{'id': 99, 'type': 'ban', 'value': '198.51.100.3'}],
    },
])


def _proc(returncode=0, stdout='', stderr=''):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def linux(monkeypatch):
    """Pretend we're on Linux with cscli installed."""
    monkeypatch.setattr(svc_mod.os, 'name', 'posix')
    monkeypatch.setattr(svc_mod, 'is_command_available', lambda c: True)


@pytest.fixture
def calls(monkeypatch, linux):
    """Capture every cscli argv; return success with empty output."""
    seen = []

    def fake_run(cmd, timeout=None, **kwargs):
        seen.append(list(cmd))
        return _proc()

    monkeypatch.setattr(svc_mod, 'run_privileged', fake_run)
    return seen


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def test_manifest_passes_validator():
    with open(os.path.join(EXT_DIR, 'plugin.json'), encoding='utf-8') as f:
        manifest = json.load(f)
    assert plugin_service._validate_manifest(manifest) is True
    assert manifest['name'] == SLUG
    assert manifest['category'] == 'security'
    assert manifest['entry_point'] == 'crowdsec:crowdsec_bp'
    assert manifest['url_prefix'] == '/api/v1/crowdsec'
    nav = manifest['contributions']['nav'][0]
    assert nav['route'] == '/crowdsec'
    routes = manifest['contributions']['routes']
    assert {'path': 'crowdsec', 'component': 'CrowdSecPage'} in routes


def test_entry_point_resolves_to_blueprint():
    assert getattr(bp_mod, 'crowdsec_bp', None) is not None
    assert bp_mod.crowdsec_bp.name == 'crowdsec'


def test_frontend_exports_route_component():
    with open(os.path.join(EXT_DIR, 'frontend', 'index.jsx'), encoding='utf-8') as f:
        src = f.read()
    assert 'CrowdSecPage' in src


# ---------------------------------------------------------------------------
# service: parsing
# ---------------------------------------------------------------------------

def test_list_decisions_flattens_alert_nesting(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(stdout=DECISIONS_JSON))
    result = CrowdSecService.list_decisions()
    assert result['success'] is True
    assert len(result['decisions']) == 2
    first = result['decisions'][0]
    assert first['value'] == '203.0.113.7'
    assert first['type'] == 'ban'
    assert first['scope'] == 'Ip'
    assert first['duration'] == '3h59m'
    assert first['reason'] == 'crowdsecurity/ssh-bf'
    assert first['country'] == 'US'
    assert first['created_at'] == '2026-07-01T10:00:00Z'
    assert result['decisions'][1]['type'] == 'captcha'


def test_list_decisions_null_output_is_empty(monkeypatch, linux):
    # cscli prints the literal string "null" when nothing matches.
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(stdout='null\n'))
    result = CrowdSecService.list_decisions()
    assert result['success'] is True
    assert result['decisions'] == []


def test_list_alerts_normalizes(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(stdout=ALERTS_JSON))
    result = CrowdSecService.list_alerts(limit=10)
    assert result['success'] is True
    a = result['alerts'][0]
    assert a['scenario'] == 'crowdsecurity/http-probing'
    assert a['source'] == '198.51.100.3'
    assert a['events_count'] == 11
    assert a['decisions'] == 1


def test_get_status_parses_version_and_lapi(monkeypatch, linux):
    def fake_run(cmd, timeout=None, **kwargs):
        if cmd[:2] == ['cscli', 'version']:
            # cscli historically prints version info to stderr.
            return _proc(stderr='version: v1.6.8\nBuildDate: 2026-05-01\n')
        if cmd[:3] == ['cscli', 'lapi', 'status']:
            return _proc(stderr='You can successfully interact with Local API (LAPI)')
        if cmd[:2] == ['cscli', 'allowlists']:
            return _proc(stdout='[]')
        return _proc()

    monkeypatch.setattr(svc_mod, 'run_privileged', fake_run)
    monkeypatch.setattr(svc_mod.ServiceControl, 'is_active',
                        staticmethod(lambda s: True))
    status = CrowdSecService.get_status()
    assert status['installed'] is True
    assert status['running'] is True
    assert status['version'] == '1.6.8'
    assert status['lapi_ok'] is True
    assert status['allowlists_supported'] is True
    assert status['docs_url']


def test_invalid_json_is_clean_error(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(stdout='not json {'))
    result = CrowdSecService.list_decisions()
    assert result['success'] is False
    assert 'JSON' in result['error']


# ---------------------------------------------------------------------------
# service: argv construction
# ---------------------------------------------------------------------------

def test_add_decision_builds_correct_argv(calls):
    result = CrowdSecService.add_decision('203.0.113.7', duration='4h', reason='bad actor')
    assert result['success'] is True
    assert calls == [[
        'cscli', 'decisions', 'add', '--ip', '203.0.113.7',
        '--duration', '4h', '--reason', 'bad actor', '--type', 'ban',
    ]]


def test_add_decision_range_uses_range_flag(calls):
    result = CrowdSecService.add_decision('203.0.113.0/24', duration='1h', reason='sweep')
    assert result['success'] is True
    assert calls[0][:5] == ['cscli', 'decisions', 'add', '--range', '203.0.113.0/24']


def test_delete_decision_builds_correct_argv(calls):
    result = CrowdSecService.delete_decision('203.0.113.7')
    assert result['success'] is True
    assert calls == [['cscli', 'decisions', 'delete', '--ip', '203.0.113.7']]


def test_add_decision_rejects_bad_input(calls):
    assert CrowdSecService.add_decision('not-an-ip')['success'] is False
    assert CrowdSecService.add_decision('1.2.3.4; rm -rf /')['success'] is False
    assert CrowdSecService.add_decision('1.2.3.4', duration='4 hours')['success'] is False
    assert calls == []  # nothing ever reached cscli


def test_allowlist_add_builds_correct_argv(calls):
    result = CrowdSecService.add_allowlist_entry(
        'trusted', '10.0.0.0/8', expiration='24h', comment='office')
    assert result['success'] is True
    assert calls == [[
        'cscli', 'allowlists', 'add', 'trusted', '10.0.0.0/8',
        '--expiration', '24h', '--comment', 'office',
    ]]


# ---------------------------------------------------------------------------
# service: feature detection + not-installed
# ---------------------------------------------------------------------------

def test_allowlists_unsupported_falls_back_to_message(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(
            returncode=1, stderr='unknown command "allowlists" for "cscli"'))
    assert CrowdSecService.allowlists_supported() is False
    result = CrowdSecService.list_allowlists()
    assert result['success'] is True
    assert result['supported'] is False
    assert result['allowlists'] == []
    assert 'does not support' in result['message']


def test_allowlists_supported_when_command_exists(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(
            stdout='[{"name": "trusted", "description": "office"}]'))
    result = CrowdSecService.list_allowlists()
    assert result['supported'] is True
    assert result['allowlists'][0]['name'] == 'trusted'


def test_not_installed_is_clean(monkeypatch):
    monkeypatch.setattr(svc_mod.os, 'name', 'posix')
    monkeypatch.setattr(svc_mod, 'is_command_available', lambda c: False)
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda *a, **kw: pytest.fail('cscli must not run when not installed'))
    assert CrowdSecService.is_installed() is False
    status = CrowdSecService.get_status()
    assert status['installed'] is False
    assert status['docs_url']
    result = CrowdSecService.list_decisions()
    assert result['success'] is False
    assert result.get('not_installed') is True


def test_windows_is_unsupported(monkeypatch):
    monkeypatch.setattr(svc_mod.os, 'name', 'nt')
    assert CrowdSecService.is_installed() is False
    result = CrowdSecService._cscli(['decisions', 'list'])
    assert result['success'] is False
    assert 'Windows' in result['error']


# ---------------------------------------------------------------------------
# blueprint routes
# ---------------------------------------------------------------------------

@pytest.fixture
def cs_app(app):
    """Register the extension blueprint on the test app (name-guarded)."""
    if 'crowdsec' not in app.blueprints:
        app.register_blueprint(bp_mod.crowdsec_bp, url_prefix='/api/v1/crowdsec')
    return app


@pytest.fixture
def cs_client(cs_app):
    return cs_app.test_client()


def test_routes_require_auth(cs_client):
    assert cs_client.get('/api/v1/crowdsec/status').status_code == 401
    assert cs_client.post('/api/v1/crowdsec/decisions', json={'ip': '1.2.3.4'}).status_code == 401
    assert cs_client.delete('/api/v1/crowdsec/decisions/1.2.3.4').status_code == 401


def test_status_route(cs_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        CrowdSecService, 'get_status',
        classmethod(lambda cls: {
            'installed': True, 'running': True, 'version': '1.6.8',
            'lapi_ok': True, 'allowlists_supported': True,
            'docs_url': svc_mod.DOCS_URL,
        }))
    resp = cs_client.get('/api/v1/crowdsec/status', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['installed'] is True
    assert data['version'] == '1.6.8'


def test_decisions_routes_happy_path(cs_client, auth_headers, monkeypatch):
    monkeypatch.setattr(CrowdSecService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(
        CrowdSecService, 'list_decisions',
        classmethod(lambda cls, ip=None, scope=None, dtype=None: {
            'success': True,
            'decisions': [{'id': 42, 'value': '203.0.113.7', 'type': 'ban'}],
        }))
    resp = cs_client.get('/api/v1/crowdsec/decisions', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['decisions'][0]['value'] == '203.0.113.7'

    added = {}

    def fake_add(cls, ip, duration='4h', reason='', dtype='ban'):
        added.update(ip=ip, duration=duration, reason=reason)
        return {'success': True, 'message': 'ok'}

    monkeypatch.setattr(CrowdSecService, 'add_decision', classmethod(fake_add))
    resp = cs_client.post(
        '/api/v1/crowdsec/decisions',
        json={'ip': '203.0.113.7', 'duration': '12h', 'reason': 'test'},
        headers=auth_headers)
    assert resp.status_code == 201
    assert added == {'ip': '203.0.113.7', 'duration': '12h', 'reason': 'test'}

    monkeypatch.setattr(
        CrowdSecService, 'delete_decision',
        classmethod(lambda cls, ip: {'success': True, 'message': f'deleted {ip}'}))
    resp = cs_client.delete('/api/v1/crowdsec/decisions/203.0.113.7', headers=auth_headers)
    assert resp.status_code == 200


def test_post_decision_requires_ip(cs_client, auth_headers, monkeypatch):
    monkeypatch.setattr(CrowdSecService, 'is_installed', classmethod(lambda cls: True))
    resp = cs_client.post('/api/v1/crowdsec/decisions', json={}, headers=auth_headers)
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_routes_report_not_installed(cs_client, auth_headers, monkeypatch):
    monkeypatch.setattr(CrowdSecService, 'is_installed', classmethod(lambda cls: False))
    for method, path in [
        ('get', '/api/v1/crowdsec/decisions'),
        ('get', '/api/v1/crowdsec/alerts'),
        ('get', '/api/v1/crowdsec/allowlists'),
        ('get', '/api/v1/crowdsec/metrics'),
        ('post', '/api/v1/crowdsec/decisions'),
    ]:
        resp = getattr(cs_client, method)(path, headers=auth_headers, json={})
        assert resp.status_code == 503, path
        assert 'error' in resp.get_json()


def test_allowlists_route_unsupported_fallback(cs_client, auth_headers, monkeypatch):
    monkeypatch.setattr(CrowdSecService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(
        CrowdSecService, 'list_allowlists',
        classmethod(lambda cls: {
            'success': True, 'supported': False, 'allowlists': [],
            'message': CrowdSecService._ALLOWLISTS_UNSUPPORTED_MSG,
        }))
    resp = cs_client.get('/api/v1/crowdsec/allowlists', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['supported'] is False
    assert data['allowlists'] == []
    assert data['message']


def test_alerts_and_metrics_routes(cs_client, auth_headers, monkeypatch):
    monkeypatch.setattr(CrowdSecService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(
        CrowdSecService, 'list_alerts',
        classmethod(lambda cls, limit=50: {
            'success': True, 'alerts': [{'id': 7, 'scenario': 'x'}]}))
    monkeypatch.setattr(
        CrowdSecService, 'get_metrics',
        classmethod(lambda cls: {'success': True, 'metrics': {'acquisition': {}}}))

    resp = cs_client.get('/api/v1/crowdsec/alerts', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['alerts'][0]['id'] == 7

    resp = cs_client.get('/api/v1/crowdsec/metrics', headers=auth_headers)
    assert resp.status_code == 200
    assert 'metrics' in resp.get_json()
