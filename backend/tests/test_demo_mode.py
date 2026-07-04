"""Demo mode: mutation blocking, allowlist, env-wins precedence, demo-info."""
import pytest

from app.middleware.demo import init_demo_mode


@pytest.fixture
def demo_app(app):
    """The conftest app with the demo guard wired (not yet in create_app)."""
    init_demo_mode(app)
    # Idempotency: a second call must be a no-op (no double-registration).
    init_demo_mode(app)
    return app


@pytest.fixture
def demo_client(demo_app):
    return demo_app.test_client()


@pytest.fixture
def _no_env_flag(monkeypatch):
    monkeypatch.delenv('SERVERKIT_DEMO_MODE', raising=False)


@pytest.fixture
def _env_flag_on(monkeypatch):
    monkeypatch.setenv('SERVERKIT_DEMO_MODE', '1')


def test_flag_off_mutations_pass(_no_env_flag, demo_client, auth_headers):
    resp = demo_client.post('/api/v1/auth/login-links', json={},
                            headers=auth_headers)
    assert resp.status_code == 201  # not blocked


def test_env_flag_blocks_mutations(_env_flag_on, demo_client, auth_headers):
    resp = demo_client.post('/api/v1/auth/login-links', json={},
                            headers=auth_headers)
    assert resp.status_code == 403
    assert resp.get_json() == {'error': 'demo_mode'}

    resp = demo_client.delete('/api/v1/auth/login-links/1', headers=auth_headers)
    assert resp.status_code == 403
    assert resp.get_json() == {'error': 'demo_mode'}


def test_env_flag_get_passes(_env_flag_on, demo_client, auth_headers):
    resp = demo_client.get('/api/v1/auth/login-links', headers=auth_headers)
    assert resp.status_code == 200


def test_login_allowlisted_in_demo_mode(_env_flag_on, demo_client, auth_headers):
    # auth_headers created the 'testadmin' user with password 'testpass'
    resp = demo_client.post('/api/v1/auth/login',
                            json={'email': 'testadmin', 'password': 'testpass'})
    assert resp.status_code == 200
    assert resp.get_json()['access_token']


def test_settings_flag_blocks_mutations(_no_env_flag, demo_app, demo_client,
                                        auth_headers):
    from app.services.settings_service import SettingsService
    with demo_app.app_context():
        SettingsService.set('demo_mode', True)

    resp = demo_client.post('/api/v1/auth/login-links', json={},
                            headers=auth_headers)
    assert resp.status_code == 403
    assert resp.get_json() == {'error': 'demo_mode'}


def test_env_wins_over_setting(demo_app, demo_client, auth_headers, monkeypatch):
    from app.services.settings_service import SettingsService
    with demo_app.app_context():
        SettingsService.set('demo_mode', True)
    monkeypatch.setenv('SERVERKIT_DEMO_MODE', '0')  # env OFF overrides setting ON

    resp = demo_client.post('/api/v1/auth/login-links', json={},
                            headers=auth_headers)
    assert resp.status_code == 201


def test_demo_info_off(_no_env_flag, demo_app, demo_client):
    resp = demo_client.get('/api/v1/auth/demo-info')
    assert resp.status_code == 200
    assert resp.get_json() == {'enabled': False}

    # No demo user was created
    from app.models import User
    with demo_app.app_context():
        assert User.query.filter_by(username='demo').first() is None


def test_demo_info_on_seeds_working_readonly_user(_env_flag_on, demo_app,
                                                  demo_client):
    resp = demo_client.get('/api/v1/auth/demo-info')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['enabled'] is True
    assert data['username'] == 'demo'
    assert data['password']

    # Stable across calls
    again = demo_client.get('/api/v1/auth/demo-info').get_json()
    assert again['password'] == data['password']

    # Seeded user is a viewer and the credentials actually log in
    from app.models import User
    with demo_app.app_context():
        user = User.query.filter_by(username='demo').first()
        assert user is not None
        assert user.role == User.ROLE_VIEWER

    login = demo_client.post('/api/v1/auth/login',
                             json={'email': 'demo', 'password': data['password']})
    assert login.status_code == 200
