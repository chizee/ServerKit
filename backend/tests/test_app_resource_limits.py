"""Per-app resource limits (task #23) — validation, model, compose gen, API.

Proving points:
- CPU/memory limit validation accepts sane values and rejects junk
- Application round-trips cpu_limit/memory_limit and exposes them in to_dict
- create_docker_app emits `cpus` / `mem_limit` on the app's service block
- the ComposeEnvService override carries the limits onto the primary service
- GET /apps/<id>/resources returns limits + best-effort usage (None when
  Docker stats are unavailable, e.g. stopped app or Windows dev)
- PUT /apps/<id>/resources validates, saves, and re-applies best-effort
"""
import os

import pytest
import yaml

from app import db
from app.models import Application, User
from app.services.compose_env_service import ComposeEnvService
from app.services.docker_service import DockerService


@pytest.fixture
def owner(app):
    user = User(email='limits@test.local', username='limitsowner',
                password_hash='x', role=User.ROLE_ADMIN, is_active=True)
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def docker_app(app, owner):
    application = Application(name='limits-app', app_type='docker', status='stopped',
                              root_path='/tmp/limits-app', user_id=owner.id)
    db.session.add(application)
    db.session.commit()
    return application


# ── validation ───────────────────────────────────────────────────────────────

def test_cpu_limit_validation_accepts_positive_floats():
    assert DockerService.validate_cpu_limit('1.5') == '1.5'
    assert DockerService.validate_cpu_limit(' 2 ') == '2'
    assert DockerService.validate_cpu_limit('0.25') == '0.25'


def test_cpu_limit_validation_clears_on_empty():
    assert DockerService.validate_cpu_limit(None) is None
    assert DockerService.validate_cpu_limit('') is None
    assert DockerService.validate_cpu_limit('   ') is None


@pytest.mark.parametrize('bad', ['0', '-1', 'two', '1,5'])
def test_cpu_limit_validation_rejects_junk(bad):
    with pytest.raises(ValueError):
        DockerService.validate_cpu_limit(bad)


def test_memory_limit_validation_accepts_docker_units():
    assert DockerService.validate_memory_limit('512m') == '512m'
    assert DockerService.validate_memory_limit('2G') == '2g'       # lowercased
    assert DockerService.validate_memory_limit('1.5g') == '1.5g'
    assert DockerService.validate_memory_limit('1024k') == '1024k'


def test_memory_limit_validation_clears_on_empty():
    assert DockerService.validate_memory_limit(None) is None
    assert DockerService.validate_memory_limit('') is None


@pytest.mark.parametrize('bad', ['512', 'm512', '2tb', 'lots', '-512m', '512mb'])
def test_memory_limit_validation_rejects_junk(bad):
    with pytest.raises(ValueError):
        DockerService.validate_memory_limit(bad)


# ── model round-trip ─────────────────────────────────────────────────────────

def test_model_round_trip_and_to_dict(docker_app):
    docker_app.cpu_limit = '1.5'
    docker_app.memory_limit = '512m'
    db.session.commit()

    reloaded = Application.query.get(docker_app.id)
    assert reloaded.cpu_limit == '1.5'
    assert reloaded.memory_limit == '512m'

    payload = reloaded.to_dict()
    assert payload['cpu_limit'] == '1.5'
    assert payload['memory_limit'] == '512m'


def test_to_dict_defaults_limits_to_none(docker_app):
    payload = docker_app.to_dict()
    assert payload['cpu_limit'] is None
    assert payload['memory_limit'] is None


# ── compose generation ───────────────────────────────────────────────────────

def test_create_docker_app_emits_limits(tmp_path):
    app_path = str(tmp_path / 'stack')
    result = DockerService.create_docker_app(app_path, 'web', 'nginx:latest',
                                             cpu_limit='1.5', memory_limit='512m')
    assert result['success'] is True

    with open(os.path.join(app_path, 'docker-compose.yml')) as f:
        compose = yaml.safe_load(f)
    svc = compose['services']['web']
    assert svc['cpus'] == 1.5
    assert svc['mem_limit'] == '512m'


def test_create_docker_app_omits_limits_when_unset(tmp_path):
    app_path = str(tmp_path / 'stack')
    result = DockerService.create_docker_app(app_path, 'web', 'nginx:latest')
    assert result['success'] is True

    with open(os.path.join(app_path, 'docker-compose.yml')) as f:
        compose = yaml.safe_load(f)
    svc = compose['services']['web']
    assert 'cpus' not in svc
    assert 'mem_limit' not in svc


def test_compose_override_carries_limits_on_primary_service(tmp_path, docker_app, monkeypatch):
    """A managed compose app with limits (and no env vars) still gets a
    ServerKit override that caps the first-declared service."""
    project = tmp_path / 'proj'
    project.mkdir()
    (project / 'docker-compose.yml').write_text(
        'services:\n  web:\n    image: nginx:latest\n  db:\n    image: mysql:8.0\n'
    )
    docker_app.root_path = str(project)
    docker_app.cpu_limit = '2'
    docker_app.memory_limit = '1g'
    db.session.commit()

    from app.services.env_service import EnvService
    monkeypatch.setattr(EnvService, 'get_effective_env_for_services',
                        staticmethod(lambda app_id, names: {}))

    override_path = ComposeEnvService.refresh_for_project(str(project))
    assert override_path is not None

    with open(override_path) as f:
        override = yaml.safe_load(f)
    web = override['services']['web']            # primary (first-declared) service
    assert web['cpus'] == 2.0
    assert web['mem_limit'] == '1g'
    assert 'db' not in override['services']      # secondary services untouched


def test_compose_override_removed_when_no_env_and_no_limits(tmp_path, docker_app, monkeypatch):
    project = tmp_path / 'proj'
    project.mkdir()
    (project / 'docker-compose.yml').write_text('services:\n  web:\n    image: nginx:latest\n')
    docker_app.root_path = str(project)
    db.session.commit()

    from app.services.env_service import EnvService
    monkeypatch.setattr(EnvService, 'get_effective_env_for_services',
                        staticmethod(lambda app_id, names: {}))

    # Pre-seed a stale override; the refresh must remove it.
    (project / ComposeEnvService.OVERRIDE_NAME).write_text('services: {}\n')
    assert ComposeEnvService.refresh_for_project(str(project)) is None
    assert not os.path.exists(str(project / ComposeEnvService.OVERRIDE_NAME))


# ── API ──────────────────────────────────────────────────────────────────────

def _make_api_app(status='stopped', **kwargs):
    owner = User.query.filter_by(username='testadmin').first()
    application = Application(name='api-limits', app_type='docker', status=status,
                              root_path='/tmp/api-limits', user_id=owner.id, **kwargs)
    db.session.add(application)
    db.session.commit()
    return application


def test_api_get_resources_stopped_app_usage_none(client, auth_headers, app):
    application = _make_api_app()
    resp = client.get(f'/api/v1/apps/{application.id}/resources', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data == {'cpu_limit': None, 'memory_limit': None, 'usage': None}


def test_api_get_resources_running_app_parses_stats(client, auth_headers, app, monkeypatch):
    application = _make_api_app(status='running')
    application.cpu_limit = '1.5'
    application.memory_limit = '512m'
    db.session.commit()

    monkeypatch.setattr(DockerService, 'get_app_container_id',
                        classmethod(lambda cls, a: 'cid123'))
    monkeypatch.setattr(DockerService, 'get_container_stats',
                        staticmethod(lambda cid: {
                            'CPUPerc': '12.34%',
                            'MemPerc': '25.00%',
                            'MemUsage': '128MiB / 512MiB',
                        }))

    resp = client.get(f'/api/v1/apps/{application.id}/resources', headers=auth_headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['cpu_limit'] == '1.5'
    assert data['memory_limit'] == '512m'
    assert data['usage'] == {
        'cpu_percent': 12.34,
        'memory_percent': 25.0,
        'memory_usage': '128MiB',
        'memory_limit': '512MiB',
    }


def test_api_get_resources_stats_failure_is_clean(client, auth_headers, app, monkeypatch):
    """Docker unreachable (e.g. Windows dev) → usage is None, not a 500."""
    application = _make_api_app(status='running')
    monkeypatch.setattr(DockerService, 'get_app_container_id',
                        classmethod(lambda cls, a: (_ for _ in ()).throw(OSError('no docker'))))

    resp = client.get(f'/api/v1/apps/{application.id}/resources', headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()['usage'] is None


def test_api_put_resources_saves_stopped_app(client, auth_headers, app):
    application = _make_api_app()
    resp = client.put(f'/api/v1/apps/{application.id}/resources', headers=auth_headers,
                      json={'cpu_limit': '1.5', 'memory_limit': '512M'})
    assert resp.status_code == 200, resp.get_json()
    data = resp.get_json()
    assert data['cpu_limit'] == '1.5'
    assert data['memory_limit'] == '512m'   # normalized to lowercase
    assert data['applied'] is False
    assert 'note' not in data               # stopped → nothing to re-apply

    reloaded = Application.query.get(application.id)
    assert reloaded.cpu_limit == '1.5'
    assert reloaded.memory_limit == '512m'


def test_api_put_resources_clears_with_null(client, auth_headers, app):
    application = _make_api_app(cpu_limit='2', memory_limit='1g')
    resp = client.put(f'/api/v1/apps/{application.id}/resources', headers=auth_headers,
                      json={'cpu_limit': None, 'memory_limit': ''})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['cpu_limit'] is None
    assert data['memory_limit'] is None


@pytest.mark.parametrize('body', [
    {'cpu_limit': '-1'},
    {'cpu_limit': 'lots'},
    {'memory_limit': '512'},
    {'memory_limit': 'huge'},
])
def test_api_put_resources_rejects_invalid(client, auth_headers, app, body):
    application = _make_api_app()
    resp = client.put(f'/api/v1/apps/{application.id}/resources', headers=auth_headers,
                      json=body)
    assert resp.status_code == 400
    assert 'error' in resp.get_json()


def test_api_put_resources_reapplies_running_local_compose(client, auth_headers, app, monkeypatch):
    application = _make_api_app(status='running')
    calls = {}

    def fake_compose_up(project_path, detach=True, build=False, compose_file=None):
        calls['path'] = project_path
        return {'success': True, 'output': ''}

    monkeypatch.setattr(DockerService, 'compose_up', staticmethod(fake_compose_up))

    resp = client.put(f'/api/v1/apps/{application.id}/resources', headers=auth_headers,
                      json={'cpu_limit': '1', 'memory_limit': '256m'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['applied'] is True
    assert calls['path'] == application.root_path


def test_api_put_resources_running_reapply_failure_notes_restart(client, auth_headers, app, monkeypatch):
    application = _make_api_app(status='running')
    monkeypatch.setattr(DockerService, 'compose_up',
                        staticmethod(lambda *a, **k: {'success': False, 'error': 'boom'}))

    resp = client.put(f'/api/v1/apps/{application.id}/resources', headers=auth_headers,
                      json={'memory_limit': '256m'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['applied'] is False
    assert data['note'] == 'restart required'
    # The limit is still saved even though the live re-apply failed.
    assert Application.query.get(application.id).memory_limit == '256m'


def test_api_get_resources_404_for_missing_app(client, auth_headers, app):
    resp = client.get('/api/v1/apps/999999/resources', headers=auth_headers)
    assert resp.status_code == 404
