"""Proving tests for Phase 4 — push re-sync + events (plan 17)."""

import pytest
import yaml

import app.models.application_manifest  # noqa: F401
from app.services.manifest_sync_service import ManifestSyncService


@pytest.fixture
def owner(app):
    from app import db
    from app.models import User
    user = User.query.filter_by(username='testadmin').first()
    if not user:
        user = User(username='testadmin', email='a@b.co', role='admin')
        db.session.add(user)
        db.session.commit()
    return user


@pytest.fixture
def project(app):
    from app import db
    from app.models import Project, Environment
    from app.services.workspace_service import WorkspaceService
    ws = WorkspaceService.ensure_default_workspace()
    proj = Project(workspace_id=ws.id, name='Sync', slug='sync')
    db.session.add(proj)
    db.session.commit()
    env = Environment(project_id=proj.id, name='Prod', slug='prod', is_default=True)
    db.session.add(env)
    db.session.commit()
    return proj


def _app_with_repo(project, owner, tmp_path, manifest_dict):
    from app import db
    from app.models import Application
    (tmp_path / 'serverkit.yaml').write_text(yaml.safe_dump(manifest_dict), encoding='utf-8')
    a = Application(name='api', app_type='docker', port=8000, user_id=owner.id,
                    project_id=project.id, root_path=str(tmp_path), status='running')
    db.session.add(a)
    db.session.commit()
    return a


@pytest.fixture
def events(monkeypatch):
    captured = []
    from app.plugins_sdk import notify
    monkeypatch.setattr(notify, 'send',
                        lambda event, to=None, data=None, **kw: captured.append((event, data)))
    return captured


def test_autodeploy_service_auto_applies(project, owner, tmp_path, events):
    m = {'version': 1, 'services': [
        {'name': 'api', 'type': 'web', 'port': 9100, 'autoDeploy': True,
         'envVars': [{'key': 'LOG_LEVEL', 'value': 'debug'}]}]}
    a = _app_with_repo(project, owner, tmp_path, m)

    result = ManifestSyncService.resync_for_app(a.id, commit='deadbeef')
    assert result['synced'] is True
    assert result['action'] == 'auto_apply'

    from app.models.application_manifest import ApplicationManifest
    row = ApplicationManifest.query.filter_by(project_id=project.id).first()
    assert row.status == 'applied'
    assert row.source_commit == 'deadbeef'
    # port change from the manifest was applied
    from app.models import Application
    assert Application.query.get(a.id).port == 9100
    assert any(e[0] == 'manifest.applied' for e in events)


def test_no_autodeploy_flips_pending(project, owner, tmp_path, events):
    m = {'version': 1, 'services': [
        {'name': 'api', 'type': 'web', 'port': 9100}]}  # autoDeploy defaults false
    a = _app_with_repo(project, owner, tmp_path, m)

    result = ManifestSyncService.resync_for_app(a.id, commit='c1')
    assert result['action'] == 'pending'
    from app.models.application_manifest import ApplicationManifest
    row = ApplicationManifest.query.filter_by(project_id=project.id).first()
    assert row.status == 'pending'
    # not applied: port unchanged
    from app.models import Application
    assert Application.query.get(a.id).port == 8000
    assert any(e[0] == 'manifest.pending' for e in events)


def test_unchanged_hash_is_noop(project, owner, tmp_path, events):
    m = {'version': 1, 'services': [
        {'name': 'api', 'type': 'web', 'port': 9100, 'autoDeploy': True}]}
    a = _app_with_repo(project, owner, tmp_path, m)

    first = ManifestSyncService.resync_for_app(a.id, commit='c1')
    assert first['synced'] is True
    second = ManifestSyncService.resync_for_app(a.id, commit='c2')
    assert second['synced'] is False
    assert second['reason'] == 'unchanged'


def test_no_manifest_is_noop(project, owner, tmp_path):
    from app import db
    from app.models import Application
    # repo dir with no serverkit.yaml
    a = Application(name='api', app_type='docker', user_id=owner.id,
                    project_id=project.id, root_path=str(tmp_path), status='running')
    db.session.add(a)
    db.session.commit()
    result = ManifestSyncService.resync_for_app(a.id)
    assert result['synced'] is False
    assert result['reason'] == 'no v1 manifest'
