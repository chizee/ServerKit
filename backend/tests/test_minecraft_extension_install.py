"""Prove the serverkit-minecraft extension wires up (plan 53 Phase 1).

Installing the builtin registers /api/v1/minecraft, creates its extension-owned
ext_serverkit_minecraft_* tables (models:register, D6), and its list route
responds — which also exercises the dashed-package import bridge reaching gamekit.
The create/console/backup Docker flow is verified separately on the dev box; this
locks the offline wiring.
"""
import sys

import pytest

import app as app_pkg
from app import db
from app.models.plugin import InstalledPlugin
from app.services import plugin_service

SLUG = 'serverkit-minecraft'
_PKG = f'app.plugins.{SLUG}'


@pytest.fixture
def install_dirs(tmp_path, monkeypatch):
    backend = tmp_path / 'plugins_backend'
    frontend = tmp_path / 'plugins_frontend'
    backend.mkdir()
    frontend.mkdir()
    monkeypatch.setattr(plugin_service, 'BACKEND_PLUGINS_DIR', str(backend))
    monkeypatch.setattr(plugin_service, 'FRONTEND_PLUGINS_DIR', str(frontend))

    added = str(backend)
    import importlib
    app_pkg_plugins = importlib.import_module('app.plugins')
    if added not in app_pkg_plugins.__path__:
        app_pkg_plugins.__path__.append(added)

    yield {'backend': backend, 'frontend': frontend}

    if added in app_pkg_plugins.__path__:
        app_pkg_plugins.__path__.remove(added)
    for name in list(sys.modules):
        if name == _PKG or name.startswith(_PKG + '.'):
            del sys.modules[name]


def test_minecraft_builtin_is_available(app):
    available = {e['slug'] for e in plugin_service.list_builtin_extensions()}
    assert SLUG in available, 'serverkit-minecraft builtin folder should exist'


def test_install_registers_routes_and_models(app, client, auth_headers, install_dirs):
    plugin = plugin_service.install_builtin_extension(SLUG)
    assert plugin.status == InstalledPlugin.STATUS_ACTIVE
    assert plugin.has_backend is True
    assert plugin.url_prefix == '/api/v1/minecraft'

    # extension-owned tables were created (models:register + create_all)
    insp = db.inspect(db.engine)
    tables = set(insp.get_table_names())
    assert 'ext_serverkit_minecraft_servers' in tables
    assert 'ext_serverkit_minecraft_backups' in tables

    # the list route responds (proves blueprint mount + dashed-import to gamekit)
    resp = client.get('/api/v1/minecraft', headers=auth_headers)
    assert resp.status_code == 200, resp.status_code
    assert resp.get_json() == {'servers': []}


def test_uninstall_removes_plugin(app, install_dirs):
    plugin = plugin_service.install_builtin_extension(SLUG)
    assert plugin_service.uninstall_plugin(plugin.id) is True
    assert InstalledPlugin.query.filter_by(slug=SLUG).first() is None
