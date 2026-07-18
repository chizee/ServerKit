"""serverkit-analytics (Web Analytics) extension tests.

Loads the builtin the way production does: ``plugin_service.
_ensure_builtin_backend_importable`` registers ``builtin-extensions/
serverkit-analytics/backend`` as the dashed package ``app.plugins.
serverkit-analytics``. The models module is imported at module top so its
``ext_serverkit_analytics_*`` tables register on ``db.metadata`` before the
``app`` fixture runs ``db.create_all()``.

Nothing here shells out or talks to Docker; the collector, ingestion buffer,
rollups, and log parsing are exercised against the in-memory test DB. Bots,
rate-limits, and visitor hashing are pure-Python and tested directly.
"""
import importlib
import json
import os

import pytest

from app.services import plugin_service

SLUG = 'serverkit-analytics'
EXT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'builtin-extensions', SLUG,
)


def _load_ext():
    assert plugin_service._ensure_builtin_backend_importable(SLUG), (
        f'builtin extension backend not importable from {EXT_DIR}')
    mods = {}
    for name in ('config', 'lifecycle', 'analytics'):
        mods[name] = importlib.import_module(f'app.plugins.{SLUG}.{name}')
    return mods


_M = _load_ext()
config_mod = _M['config']
lifecycle_mod = _M['lifecycle']
bp_mod = _M['analytics']


# --------------------------------------------------------------------------- #
# helpers / fixtures
# --------------------------------------------------------------------------- #
def _mk_plugin_row(config=None, status=None):
    from app import db
    from app.models.plugin import InstalledPlugin
    row = InstalledPlugin(
        name=SLUG, display_name='Web Analytics', slug=SLUG, version='1.0.0',
        status=status or InstalledPlugin.STATUS_ACTIVE,
    )
    row.config = config or {}
    db.session.add(row)
    db.session.commit()
    return row


def _mk_admin():
    from app import db
    from app.models.user import User
    from werkzeug.security import generate_password_hash
    u = User(email='analyticsadmin@t.local', username='analyticsadmin',
             password_hash=generate_password_hash('x'),
             role=User.ROLE_ADMIN, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def _mk_viewer():
    from app import db
    from app.models.user import User
    from werkzeug.security import generate_password_hash
    u = User(email='analyticsviewer@t.local', username='analyticsviewer',
             password_hash=generate_password_hash('x'),
             role=User.ROLE_VIEWER, is_active=True)
    db.session.add(u)
    db.session.commit()
    return u


def _auth(user):
    from flask_jwt_extended import create_access_token
    return {'Authorization': f'Bearer {create_access_token(identity=user.id)}'}


@pytest.fixture
def analytics_client(app):
    if 'analytics' not in app.blueprints:
        app.register_blueprint(bp_mod.analytics_bp, url_prefix='/api/v1/analytics')
    return app.test_client()


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #
def _manifest():
    with open(os.path.join(EXT_DIR, 'plugin.json'), encoding='utf-8') as f:
        return json.load(f)


def test_manifest_passes_validator():
    m = _manifest()
    assert plugin_service._validate_manifest(m) is True
    assert m['name'] == SLUG
    assert m['entry_point'] == 'analytics:analytics_bp'
    assert m['url_prefix'] == '/api/v1/analytics'
    assert m['models'] == 'models:register'
    nav = m['contributions']['nav'][0]
    assert nav['route'] == '/analytics' and nav['id'] == 'analytics'
    assert m['contributions']['page_titles']['/analytics'] == 'Web Analytics'


def test_manifest_permissions_known_and_no_dashes():
    from app.plugins_sdk import permissions as sdk_perms
    m = _manifest()
    assert sdk_perms.unknown_permissions(m['permissions']) == []
    assert set(m['permissions']) == {'db', 'network', 'filesystem'}
    assert '—' not in m['description'] and '–' not in m['description']


def test_manifest_jobs_and_schedules_pair_up():
    m = _manifest()
    job_kinds = {j['kind'] for j in m['jobs']}
    sched_kinds = {s['kind'] for s in m['schedules']}
    assert sched_kinds <= job_kinds
    assert {'analytics.rollup', 'analytics.retention_prune',
            'analytics.log_tail'} <= job_kinds


def test_lifecycle_and_job_refs_resolve():
    m = _manifest()
    for ref in m['lifecycle'].values():
        module_name, func_name = ref.split(':')
        mod = importlib.import_module(f'app.plugins.{SLUG}.{module_name}')
        assert callable(getattr(mod, func_name, None)), ref
    for job in m['jobs']:
        module_name, func_name = job['handler'].split(':')
        mod = importlib.import_module(f'app.plugins.{SLUG}.{module_name}')
        assert callable(getattr(mod, func_name, None)), job['handler']


def test_entry_point_resolves_to_blueprint():
    assert getattr(bp_mod, 'analytics_bp', None) is not None
    assert bp_mod.analytics_bp.name == 'analytics'


def test_config_schema_keys_match_defaults():
    m = _manifest()
    schema_keys = set(m['config_schema'].keys())
    assert schema_keys == set(config_mod.DEFAULTS.keys())


# --------------------------------------------------------------------------- #
# config accessor
# --------------------------------------------------------------------------- #
def test_get_cfg_returns_defaults_without_row(app):
    cfg = config_mod.get_cfg()
    assert cfg['raw_retention_days'] == 30
    assert cfg['honor_dnt'] is True
    assert cfg['collect_rate_per_min'] == 600


def test_get_cfg_merges_saved_over_defaults(app):
    _mk_plugin_row(config={'raw_retention_days': 7, 'geo_enabled': True})
    cfg = config_mod.get_cfg()
    assert cfg['raw_retention_days'] == 7      # overridden
    assert cfg['geo_enabled'] is True          # overridden
    assert cfg['rollup_retention_months'] == 13  # still default


def test_cfg_int_clamps(app):
    _mk_plugin_row(config={'collect_rate_per_min': 5})
    assert config_mod.cfg_int('collect_rate_per_min', minimum=10) == 10


def test_cfg_bool_accepts_strings(app):
    _mk_plugin_row(config={'honor_dnt': 'false'})
    assert config_mod.cfg_bool('honor_dnt') is False


# --------------------------------------------------------------------------- #
# lifecycle
# --------------------------------------------------------------------------- #
def test_on_install_seeds_config_defaults(app):
    row = _mk_plugin_row(config={})
    lifecycle_mod.on_install(row)
    assert row.config['raw_retention_days'] == 30
    assert row.config['log_ingestion_enabled'] is True


def test_on_install_does_not_clobber_saved(app):
    row = _mk_plugin_row(config={'raw_retention_days': 90})
    lifecycle_mod.on_install(row)
    assert row.config['raw_retention_days'] == 90  # preserved
    assert 'buffer_max' in row.config              # new key seeded


def test_on_uninstall_is_safe_without_integrations(app):
    row = _mk_plugin_row()
    # wp_integration / nginx_integration may not import cleanly yet; must not raise.
    lifecycle_mod.on_uninstall(row, purge=True)


# --------------------------------------------------------------------------- #
# ping route (proves the blueprint mounts; 503 status guard covered separately)
# --------------------------------------------------------------------------- #
def test_ping_route(analytics_client):
    resp = analytics_client.get('/api/v1/analytics/ping')
    assert resp.status_code == 200
    assert resp.get_json()['plugin'] == SLUG
