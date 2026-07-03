"""serverkit-dns-server extension tests (Panel Improvements #28).

Covers: manifest validity, install argv construction (docker stubbed) incl.
the localhost-only API binding and generated-api-key persistence, zone
creation SOA/NS bootstrap, rrset upsert/delete PowerDNS API call shapes
(requests stubbed), record-type/name validation, DNSSEC enable returning DS
records, the hand-rolled delegation-check DNS parser on fixture packet
bytes, and blueprint auth/503/happy paths with the service stubbed.

The extension backend is loaded exactly the way production loads builtins:
``plugin_service._ensure_builtin_backend_importable`` registers
``builtin-extensions/serverkit-dns-server/backend`` as
``app.plugins.serverkit-dns-server``.
"""
import importlib
import json
import os
import struct
from types import SimpleNamespace

import pytest

from app.services import plugin_service

SLUG = 'serverkit-dns-server'
EXT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'builtin-extensions', SLUG,
)


def _load_ext():
    assert plugin_service._ensure_builtin_backend_importable(SLUG), (
        f'builtin extension backend not importable from {EXT_DIR}')
    svc_mod = importlib.import_module(f'app.plugins.{SLUG}.dns_server_service')
    bp_mod = importlib.import_module(f'app.plugins.{SLUG}.dns_server')
    return svc_mod, bp_mod


svc_mod, bp_mod = _load_ext()
DnsServerService = svc_mod.DnsServerService

CFG = {
    'api_key': 'test-api-key',
    'ns_hostname': 'ns1.example.com',
    'admin_email': 'hostmaster@example.com',
}


def _proc(returncode=0, stdout='', stderr=''):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class FakeResponse:
    def __init__(self, status_code=200, data=None, text=''):
        self.status_code = status_code
        self._data = data
        self.text = text or (json.dumps(data) if data is not None else '')
        self.content = self.text.encode()

    def json(self):
        if self._data is None:
            raise ValueError('no json')
        return self._data


@pytest.fixture
def linux(monkeypatch):
    """Pretend we're on Linux with docker installed and config saved."""
    monkeypatch.setattr(svc_mod.os, 'name', 'posix')
    monkeypatch.setattr(svc_mod, 'is_command_available', lambda c: True)
    monkeypatch.setattr(DnsServerService, '_config', classmethod(lambda cls: dict(CFG)))


@pytest.fixture
def api_calls(monkeypatch, linux):
    """Capture every PowerDNS API request; return success with empty body."""
    seen = []

    def fake_request(method, url, headers=None, json=None, timeout=None):
        seen.append({'method': method, 'url': url, 'headers': headers, 'json': json})
        return FakeResponse(204, None, '')

    monkeypatch.setattr(svc_mod.requests, 'request', fake_request)
    return seen


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------

def test_manifest_passes_validator():
    with open(os.path.join(EXT_DIR, 'plugin.json'), encoding='utf-8') as f:
        manifest = json.load(f)
    assert plugin_service._validate_manifest(manifest) is True
    assert manifest['name'] == SLUG
    assert manifest['category'] == 'networking'
    assert set(manifest['permissions']) == {'shell', 'docker'}
    assert manifest['entry_point'] == 'dns_server:dns_server_bp'
    assert manifest['url_prefix'] == '/api/v1/dns-server'
    nav = manifest['contributions']['nav'][0]
    assert nav['route'] == '/dns-server'
    routes = manifest['contributions']['routes']
    assert {'path': 'dns-server', 'component': 'DnsServerPage'} in routes
    assert manifest['contributions']['page_titles']['/dns-server'] == 'DNS Server'


def test_manifest_permissions_are_known():
    from app.plugins_sdk import permissions as sdk_perms
    with open(os.path.join(EXT_DIR, 'plugin.json'), encoding='utf-8') as f:
        manifest = json.load(f)
    assert sdk_perms.unknown_permissions(manifest['permissions']) == []


def test_entry_point_resolves_to_blueprint():
    assert getattr(bp_mod, 'dns_server_bp', None) is not None
    assert bp_mod.dns_server_bp.name == 'dns_server'


def test_frontend_exports_route_component():
    with open(os.path.join(EXT_DIR, 'frontend', 'index.jsx'), encoding='utf-8') as f:
        src = f.read()
    assert 'export { default as DnsServerPage }' in src
    # No module-level default export: PluginLoader legacy-auto-renders those.
    assert 'export default' not in src


# ---------------------------------------------------------------------------
# service: install / uninstall argv
# ---------------------------------------------------------------------------

def test_install_builds_correct_docker_run(monkeypatch, linux):
    calls = []
    saved = {}

    def fake_run(cmd, timeout=None, **kwargs):
        calls.append(list(cmd))
        if cmd[:2] == ['docker', 'inspect']:
            return _proc(returncode=1, stderr='No such object')
        return _proc(stdout='abc123\n')

    monkeypatch.setattr(svc_mod, 'run_privileged', fake_run)
    monkeypatch.setattr(DnsServerService, '_save_config',
                        classmethod(lambda cls, updates: saved.update(updates) or True))

    result = DnsServerService.install('NS1.Example.COM.', 'hostmaster@example.com')
    assert result['success'] is True, result

    # Data dir created, container started.
    assert ['mkdir', '-p', svc_mod.DATA_DIR] in calls
    run_cmd = next(c for c in calls if c[:2] == ['docker', 'run'])

    # Port 53 published tcp+udp; API published on loopback ONLY.
    assert '53:53/udp' in run_cmd
    assert '53:53/tcp' in run_cmd
    assert '127.0.0.1:8081:8081' in run_cmd
    assert not any(a == '8081:8081' for a in run_cmd)

    # SQLite volume + official image.
    assert f'{svc_mod.DATA_DIR}:{svc_mod.CONTAINER_DB_DIR}' in run_cmd
    assert svc_mod.IMAGE in run_cmd
    assert '--restart' in run_cmd

    # API enabled with a generated key... that was persisted to the config store.
    assert '--api=yes' in run_cmd
    key_args = [a for a in run_cmd if a.startswith('--api-key=')]
    assert len(key_args) == 1
    generated = key_args[0].split('=', 1)[1]
    assert len(generated) == 48  # token_hex(24)
    assert saved['api_key'] == generated
    assert saved['ns_hostname'] == 'ns1.example.com'
    assert saved['admin_email'] == 'hostmaster@example.com'


def test_install_rejects_bad_params(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda *a, **kw: pytest.fail('docker must not run on invalid input'))
    assert DnsServerService.install('', 'a@b.co')['success'] is False
    assert DnsServerService.install('not a hostname!', 'a@b.co')['success'] is False
    assert DnsServerService.install('ns1.example.com', 'not-an-email')['success'] is False
    assert DnsServerService.install('ns1.example.com', '')['success'] is False


def test_install_refuses_when_container_exists(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(stdout='true\n'))  # inspect succeeds
    result = DnsServerService.install('ns1.example.com', 'hostmaster@example.com')
    assert result['success'] is False
    assert 'already exists' in result['error']


def test_uninstall_keep_data_leaves_data_dir(monkeypatch, linux):
    calls = []

    def fake_run(cmd, timeout=None, **kwargs):
        calls.append(list(cmd))
        return _proc()

    monkeypatch.setattr(svc_mod, 'run_privileged', fake_run)
    monkeypatch.setattr(DnsServerService, '_save_config',
                        classmethod(lambda cls, updates: True))

    result = DnsServerService.uninstall(keep_data=True)
    assert result['success'] is True
    assert ['docker', 'rm', '-f', svc_mod.CONTAINER_NAME] in calls
    assert not any(c[:1] == ['rm'] for c in calls)

    calls.clear()
    result = DnsServerService.uninstall(keep_data=False)
    assert result['success'] is True
    assert ['rm', '-rf', svc_mod.DATA_DIR] in calls


def test_windows_is_unsupported(monkeypatch):
    monkeypatch.setattr(svc_mod.os, 'name', 'nt')
    assert DnsServerService.is_installed() is False
    result = DnsServerService.install('ns1.example.com', 'a@b.co')
    assert result['success'] is False
    assert 'Windows' in result['error']
    status = DnsServerService.get_status()
    assert status['installed'] is False
    assert status['authoritative_only'] is True


# ---------------------------------------------------------------------------
# service: status
# ---------------------------------------------------------------------------

def test_status_running_reads_version_from_api(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(stdout='true\n'))
    monkeypatch.setattr(
        svc_mod.requests, 'request',
        lambda method, url, **kw: FakeResponse(200, {'version': '4.9.3'}))
    status = DnsServerService.get_status()
    assert status['installed'] is True
    assert status['running'] is True
    assert status['version'] == '4.9.3'
    assert status['ns_hostname'] == 'ns1.example.com'


def test_status_not_installed(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod, 'run_privileged',
        lambda cmd, timeout=None, **kw: _proc(returncode=1, stderr='No such object'))
    status = DnsServerService.get_status()
    assert status['installed'] is False
    assert status['running'] is False


# ---------------------------------------------------------------------------
# service: zones + rrsets (PowerDNS API call shapes)
# ---------------------------------------------------------------------------

def test_create_zone_bootstraps_soa_and_ns(api_calls):
    result = DnsServerService.create_zone('Example.COM')
    assert result['success'] is True, result
    assert len(api_calls) == 1
    call = api_calls[0]
    assert call['method'] == 'POST'
    assert call['url'].endswith('/servers/localhost/zones')
    assert call['url'].startswith('http://127.0.0.1:8081')
    assert call['headers']['X-API-Key'] == 'test-api-key'

    payload = call['json']
    assert payload['name'] == 'example.com.'
    assert payload['kind'] == 'Native'
    rrsets = {r['type']: r for r in payload['rrsets']}
    assert rrsets['SOA']['records'][0]['content'] == (
        'ns1.example.com. hostmaster.example.com. 1 10800 3600 604800 3600')
    assert rrsets['NS']['records'][0]['content'] == 'ns1.example.com.'
    assert all(r['name'] == 'example.com.' for r in payload['rrsets'])


def test_create_zone_rejects_junk(api_calls):
    assert DnsServerService.create_zone('')['success'] is False
    assert DnsServerService.create_zone('no spaces allowed.com')['success'] is False
    assert DnsServerService.create_zone('*.example.com')['success'] is False
    assert api_calls == []


def test_upsert_rrset_builds_replace_patch(api_calls):
    result = DnsServerService.upsert_rrset(
        'example.com', 'www', 'a', 300, ['203.0.113.7', '203.0.113.8'])
    assert result['success'] is True, result
    call = api_calls[0]
    assert call['method'] == 'PATCH'
    assert call['url'].endswith('/servers/localhost/zones/example.com.')
    rrset = call['json']['rrsets'][0]
    assert rrset['name'] == 'www.example.com.'
    assert rrset['type'] == 'A'
    assert rrset['ttl'] == 300
    assert rrset['changetype'] == 'REPLACE'
    assert rrset['records'] == [
        {'content': '203.0.113.7', 'disabled': False},
        {'content': '203.0.113.8', 'disabled': False},
    ]


def test_upsert_rrset_apex_and_absolute_names(api_calls):
    assert DnsServerService.upsert_rrset(
        'example.com', '@', 'TXT', 3600, ['"v=spf1 -all"'])['success'] is True
    assert api_calls[-1]['json']['rrsets'][0]['name'] == 'example.com.'

    assert DnsServerService.upsert_rrset(
        'example.com', 'mail.example.com.', 'MX', 3600,
        ['10 mail.example.com.'])['success'] is True
    assert api_calls[-1]['json']['rrsets'][0]['name'] == 'mail.example.com.'


def test_rrset_validation_rejects_junk(api_calls):
    # Unknown record type.
    assert DnsServerService.upsert_rrset(
        'example.com', 'www', 'ANAME', 300, ['x'])['success'] is False
    # Out-of-zone absolute name.
    assert DnsServerService.upsert_rrset(
        'example.com', 'www.other.org.', 'A', 300, ['1.2.3.4'])['success'] is False
    # Bad label characters.
    assert DnsServerService.upsert_rrset(
        'example.com', 'bad label', 'A', 300, ['1.2.3.4'])['success'] is False
    # Bad TTL / empty records.
    assert DnsServerService.upsert_rrset(
        'example.com', 'www', 'A', 'soon', ['1.2.3.4'])['success'] is False
    assert DnsServerService.upsert_rrset(
        'example.com', 'www', 'A', 300, [])['success'] is False
    # SOA delete is refused.
    assert DnsServerService.delete_rrset(
        'example.com', '@', 'SOA')['success'] is False
    assert api_calls == []  # nothing ever reached the PowerDNS API


def test_delete_rrset_builds_delete_patch(api_calls):
    result = DnsServerService.delete_rrset('example.com', 'www', 'A')
    assert result['success'] is True
    rrset = api_calls[0]['json']['rrsets'][0]
    assert rrset['changetype'] == 'DELETE'
    assert rrset['name'] == 'www.example.com.'
    assert rrset['records'] == []


def test_wildcard_record_names_allowed(api_calls):
    result = DnsServerService.upsert_rrset(
        'example.com', '*', 'A', 300, ['203.0.113.7'])
    assert result['success'] is True
    assert api_calls[0]['json']['rrsets'][0]['name'] == '*.example.com.'


# ---------------------------------------------------------------------------
# service: DNSSEC
# ---------------------------------------------------------------------------

def test_dnssec_enable_returns_ds_records(monkeypatch, linux):
    calls = []
    DS = ['12345 13 2 aabbccdd...', '12345 13 4 eeff0011...']

    def fake_request(method, url, headers=None, json=None, timeout=None):
        calls.append({'method': method, 'url': url, 'json': json})
        if method == 'GET' and url.endswith('/cryptokeys'):
            return FakeResponse(200, [
                {'active': True, 'ds': DS},
                {'active': False, 'ds': ['ignored inactive key']},
            ])
        return FakeResponse(204, None, '')

    monkeypatch.setattr(svc_mod.requests, 'request', fake_request)
    result = DnsServerService.set_dnssec('example.com', True)
    assert result['success'] is True
    assert result['dnssec'] is True
    assert result['ds_records'] == DS

    put = calls[0]
    assert put['method'] == 'PUT'
    assert put['url'].endswith('/servers/localhost/zones/example.com.')
    assert put['json'] == {'dnssec': True, 'api_rectify': True}


def test_dnssec_disable(api_calls):
    result = DnsServerService.set_dnssec('example.com', False)
    assert result['success'] is True
    assert result['dnssec'] is False
    assert api_calls[0]['json'] == {'dnssec': False}


def test_api_error_is_clean(monkeypatch, linux):
    monkeypatch.setattr(
        svc_mod.requests, 'request',
        lambda method, url, **kw: FakeResponse(422, {'error': 'Domain already exists'}))
    result = DnsServerService.create_zone('example.com')
    assert result['success'] is False
    assert 'Domain already exists' in result['error']


def test_api_requires_key(monkeypatch, linux):
    monkeypatch.setattr(DnsServerService, '_config', classmethod(lambda cls: {}))
    monkeypatch.setattr(
        svc_mod.requests, 'request',
        lambda *a, **kw: pytest.fail('API must not be called without a key'))
    result = DnsServerService.list_zones()
    assert result['success'] is False
    assert 'API key' in result['error']


# ---------------------------------------------------------------------------
# service: delegation check (mini DNS client)
# ---------------------------------------------------------------------------

def _ns_response_packet(query_id):
    """A DNS response for `example.com NS` with two compressed NS answers."""
    header = struct.pack('>HHHHHH', query_id, 0x8180, 1, 2, 0, 0)
    qname = b'\x07example\x03com\x00'
    question = qname + struct.pack('>HH', 2, 1)
    # Answers use a compression pointer back to offset 12 for both the owner
    # name and the rdata suffix.
    ptr = b'\xc0\x0c'
    answer1 = ptr + struct.pack('>HHIH', 2, 1, 3600, 6) + b'\x03ns1' + ptr
    answer2 = ptr + struct.pack('>HHIH', 2, 1, 3600, 6) + b'\x03ns2' + ptr
    return header + question + answer1 + answer2


def test_parse_ns_response_fixture_packet():
    packet = _ns_response_packet(0x1234)
    names = DnsServerService._parse_ns_response(packet, 0x1234)
    assert names == ['ns1.example.com', 'ns2.example.com']


def test_parse_ns_response_rejects_id_mismatch():
    packet = _ns_response_packet(0x1234)
    with pytest.raises(ValueError):
        DnsServerService._parse_ns_response(packet, 0x9999)


def test_parse_ns_response_rejects_truncated():
    with pytest.raises(ValueError):
        DnsServerService._parse_ns_response(b'\x00\x01\x02', 1)


def test_build_ns_query_roundtrip():
    packet = DnsServerService._build_ns_query('example.com.', 0x4242)
    rid, flags, qdcount, ancount, _, _ = struct.unpack('>HHHHHH', packet[:12])
    assert rid == 0x4242
    assert flags == 0x0100  # RD
    assert (qdcount, ancount) == (1, 0)
    assert b'\x07example\x03com\x00' in packet
    assert packet.endswith(struct.pack('>HH', 2, 1))


def test_check_delegation_match(monkeypatch, linux):
    monkeypatch.setattr(
        DnsServerService, 'get_zone',
        classmethod(lambda cls, z: {'success': True, 'zone': {'rrsets': [
            {'name': 'example.com.', 'type': 'NS',
             'records': ['ns1.example.com.', 'ns2.example.com.']},
        ]}}))
    monkeypatch.setattr(
        DnsServerService, '_query_public_ns',
        classmethod(lambda cls, z: ['ns2.example.com', 'ns1.example.com']))
    result = DnsServerService.check_delegation('example.com')
    assert result['success'] is True
    assert result['checked'] is True
    assert result['delegated'] is True
    assert result['zone_ns'] == ['ns1.example.com', 'ns2.example.com']


def test_check_delegation_mismatch_and_unreachable(monkeypatch, linux):
    monkeypatch.setattr(
        DnsServerService, 'get_zone',
        classmethod(lambda cls, z: {'success': True, 'zone': {'rrsets': [
            {'name': 'example.com.', 'type': 'NS', 'records': ['ns1.example.com.']},
        ]}}))
    monkeypatch.setattr(
        DnsServerService, '_query_public_ns',
        classmethod(lambda cls, z: ['dns1.registrar-parking.net']))
    result = DnsServerService.check_delegation('example.com')
    assert result['delegated'] is False
    assert result['note']

    def boom(cls, z):
        raise OSError('network down')

    monkeypatch.setattr(DnsServerService, '_query_public_ns', classmethod(boom))
    result = DnsServerService.check_delegation('example.com')
    assert result['success'] is True  # best-effort, never a hard failure
    assert result['checked'] is False
    assert 'network down' in result['note']


# ---------------------------------------------------------------------------
# blueprint routes
# ---------------------------------------------------------------------------

@pytest.fixture
def dns_app(app):
    """Register the extension blueprint on the test app (name-guarded)."""
    if 'dns_server' not in app.blueprints:
        app.register_blueprint(bp_mod.dns_server_bp, url_prefix='/api/v1/dns-server')
    return app


@pytest.fixture
def dns_client(dns_app):
    return dns_app.test_client()


def test_routes_require_auth(dns_client):
    assert dns_client.get('/api/v1/dns-server/status').status_code == 401
    assert dns_client.post('/api/v1/dns-server/install', json={}).status_code == 401
    assert dns_client.get('/api/v1/dns-server/zones').status_code == 401
    assert dns_client.post('/api/v1/dns-server/zones', json={}).status_code == 401


def test_status_route(dns_client, auth_headers, monkeypatch):
    monkeypatch.setattr(
        DnsServerService, 'get_status',
        classmethod(lambda cls: {
            'installed': True, 'running': True, 'version': '4.9.3',
            'image': svc_mod.IMAGE, 'container': svc_mod.CONTAINER_NAME,
            'ns_hostname': 'ns1.example.com', 'authoritative_only': True,
            'docs_url': svc_mod.DOCS_URL,
        }))
    resp = dns_client.get('/api/v1/dns-server/status', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['installed'] is True
    assert data['version'] == '4.9.3'
    assert data['authoritative_only'] is True


def test_install_route(dns_client, auth_headers, monkeypatch):
    captured = {}

    def fake_install(cls, ns_hostname, admin_email):
        captured.update(ns=ns_hostname, email=admin_email)
        return {'success': True, 'message': 'ok', 'container': svc_mod.CONTAINER_NAME}

    monkeypatch.setattr(DnsServerService, 'install', classmethod(fake_install))
    resp = dns_client.post(
        '/api/v1/dns-server/install',
        json={'ns_hostname': 'ns1.example.com', 'admin_email': 'a@b.co'},
        headers=auth_headers)
    assert resp.status_code == 201
    assert captured == {'ns': 'ns1.example.com', 'email': 'a@b.co'}

    # Missing fields are a 400 before the service is touched.
    resp = dns_client.post('/api/v1/dns-server/install', json={}, headers=auth_headers)
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_uninstall_route_parses_keep_data(dns_client, auth_headers, monkeypatch):
    seen = {}
    monkeypatch.setattr(
        DnsServerService, 'uninstall',
        classmethod(lambda cls, keep_data=True: seen.update(keep=keep_data)
                    or {'success': True, 'message': 'removed'}))
    resp = dns_client.delete('/api/v1/dns-server/install?keep_data=false',
                             headers=auth_headers)
    assert resp.status_code == 200
    assert seen['keep'] is False
    dns_client.delete('/api/v1/dns-server/install', headers=auth_headers)
    assert seen['keep'] is True


def test_routes_report_not_installed(dns_client, auth_headers, monkeypatch):
    monkeypatch.setattr(DnsServerService, 'is_installed', classmethod(lambda cls: False))
    for method, path in [
        ('get', '/api/v1/dns-server/zones'),
        ('post', '/api/v1/dns-server/zones'),
        ('get', '/api/v1/dns-server/zones/example.com'),
        ('delete', '/api/v1/dns-server/zones/example.com'),
        ('post', '/api/v1/dns-server/zones/example.com/rrsets'),
        ('delete', '/api/v1/dns-server/zones/example.com/rrsets'),
        ('post', '/api/v1/dns-server/zones/example.com/dnssec'),
    ]:
        resp = getattr(dns_client, method)(path, headers=auth_headers, json={})
        assert resp.status_code == 503, path
        assert 'error' in resp.get_json()


def test_zones_routes_happy_path(dns_client, auth_headers, monkeypatch):
    monkeypatch.setattr(DnsServerService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(
        DnsServerService, 'list_zones',
        classmethod(lambda cls: {'success': True, 'zones': [
            {'name': 'example.com.', 'kind': 'Native', 'serial': 1, 'dnssec': False},
        ]}))
    resp = dns_client.get('/api/v1/dns-server/zones', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['zones'][0]['name'] == 'example.com.'

    monkeypatch.setattr(
        DnsServerService, 'create_zone',
        classmethod(lambda cls, name: {'success': True, 'zone': 'example.com.',
                                       'message': 'created'}))
    resp = dns_client.post('/api/v1/dns-server/zones',
                           json={'name': 'example.com'}, headers=auth_headers)
    assert resp.status_code == 201

    resp = dns_client.post('/api/v1/dns-server/zones', json={}, headers=auth_headers)
    assert resp.status_code == 400


def test_zone_detail_route_includes_ds_and_delegation(dns_client, auth_headers, monkeypatch):
    monkeypatch.setattr(DnsServerService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(
        DnsServerService, 'get_zone',
        classmethod(lambda cls, z: {'success': True, 'zone': {
            'name': 'example.com.', 'kind': 'Native', 'serial': 1,
            'dnssec': True, 'rrsets': [],
        }}))
    monkeypatch.setattr(
        DnsServerService, 'get_ds_records',
        classmethod(lambda cls, z: {'success': True, 'ds_records': ['12345 13 2 aa']}))
    monkeypatch.setattr(
        DnsServerService, 'check_delegation',
        classmethod(lambda cls, z: {'success': True, 'checked': True,
                                    'delegated': True, 'zone_ns': [],
                                    'public_ns': [], 'note': None}))
    resp = dns_client.get('/api/v1/dns-server/zones/example.com', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['zone']['dnssec'] is True
    assert data['ds_records'] == ['12345 13 2 aa']
    assert data['delegation']['delegated'] is True


def test_rrset_routes(dns_client, auth_headers, monkeypatch):
    monkeypatch.setattr(DnsServerService, 'is_installed', classmethod(lambda cls: True))
    captured = {}

    def fake_upsert(cls, zone, name, rtype, ttl, records):
        captured.update(zone=zone, name=name, rtype=rtype, ttl=ttl, records=records)
        return {'success': True, 'message': 'saved'}

    monkeypatch.setattr(DnsServerService, 'upsert_rrset', classmethod(fake_upsert))
    resp = dns_client.post(
        '/api/v1/dns-server/zones/example.com/rrsets',
        json={'name': 'www', 'type': 'A', 'ttl': 300, 'records': ['203.0.113.7']},
        headers=auth_headers)
    assert resp.status_code == 200
    assert captured == {'zone': 'example.com', 'name': 'www', 'rtype': 'A',
                        'ttl': 300, 'records': ['203.0.113.7']}

    resp = dns_client.post('/api/v1/dns-server/zones/example.com/rrsets',
                           json={'name': 'www'}, headers=auth_headers)
    assert resp.status_code == 400  # type is required

    monkeypatch.setattr(
        DnsServerService, 'delete_rrset',
        classmethod(lambda cls, zone, name, rtype: {'success': True, 'message': 'gone'}))
    resp = dns_client.delete(
        '/api/v1/dns-server/zones/example.com/rrsets?name=www&type=A',
        headers=auth_headers)
    assert resp.status_code == 200


def test_dnssec_route(dns_client, auth_headers, monkeypatch):
    monkeypatch.setattr(DnsServerService, 'is_installed', classmethod(lambda cls: True))
    monkeypatch.setattr(
        DnsServerService, 'set_dnssec',
        classmethod(lambda cls, zone, enabled: {
            'success': True, 'dnssec': enabled,
            'ds_records': ['12345 13 2 aa'] if enabled else [],
        }))
    resp = dns_client.post('/api/v1/dns-server/zones/example.com/dnssec',
                           json={'action': 'enable'}, headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['ds_records'] == ['12345 13 2 aa']

    resp = dns_client.post('/api/v1/dns-server/zones/example.com/dnssec',
                           json={'action': 'sideways'}, headers=auth_headers)
    assert resp.status_code == 400
