"""Proving tests for the `manifest` drift check (plan 17, task #18).

The check compares live app config against the stored manifest (not files on
disk). We build a project, apply a tiny port+env manifest, persist it, then
exercise in_sync -> drifted -> repair -> in_sync.
"""

import pytest

import app.models.application_manifest  # noqa: F401
from app.services.manifest_spec_service import ManifestSpecService
from app.services.manifest_apply_service import ManifestApplyService
from app.services.manifest_persistence_service import ManifestPersistenceService


# port + single literal env only — no db, no volumes, no domains, so the apply
# needs neither Docker volume creation nor domain attachment.
MANIFEST = {
    'version': 1,
    'services': [
        {
            'name': 'api', 'type': 'web', 'port': 8000,
            'envVars': [{'key': 'LOG_LEVEL', 'value': 'info'}],
        },
    ],
}


@pytest.fixture
def owner(app):
    from app import db
    from app.models import User
    user = User.query.filter_by(username='testadmin').first()
    if not user:
        user = User(username='testadmin', email='admin@test.local', role='admin')
        if hasattr(user, 'set_password'):
            user.set_password('admin')
        db.session.add(user)
        db.session.commit()
    return user


@pytest.fixture
def project(app):
    from app import db
    from app.models import Project, Environment
    from app.services.workspace_service import WorkspaceService
    ws = WorkspaceService.ensure_default_workspace()
    proj = Project(workspace_id=ws.id, name='Shop', slug='shop')
    db.session.add(proj)
    db.session.commit()
    env = Environment(project_id=proj.id, name='Production', slug='production',
                      is_default=True)
    db.session.add(env)
    db.session.commit()
    return proj


@pytest.fixture(autouse=True)
def _stub_side_effects(monkeypatch):
    # Keep Docker/DNS out of the harness even though this manifest shouldn't
    # need them — belt and suspenders, mirrors test_manifest_apply.py.
    from app.services.docker_service import DockerService
    from app.services.domain_attach_service import DomainAttachService
    monkeypatch.setattr(DockerService, 'create_volume',
                        classmethod(lambda cls, name, driver='local': {'success': True}))
    monkeypatch.setattr(DomainAttachService, 'attach',
                        classmethod(lambda cls, app, host, ssl='auto', email=None,
                                    make_primary=False: {'success': True, 'domain': host,
                                                         'created': True, 'warnings': []}))


@pytest.fixture
def applied(project, owner):
    """Apply + persist the manifest; return (project, owner, app)."""
    from app import db
    from app.models import Application
    n = ManifestSpecService.normalize(MANIFEST)
    result = ManifestApplyService.apply(project, n, user_id=owner.id)
    assert result['success'] is True, result
    # Calling the service directly does not store the manifest; persist it so
    # resolved_for_app can find it.
    ManifestPersistenceService.store_manifest(project.id, n)
    db.session.commit()
    api = Application.query.filter_by(project_id=project.id, name='api').first()
    assert api is not None
    return project, owner, api


def _find_manifest_check():
    from app.services.drift_service import DRIFT_CHECKS
    return DRIFT_CHECKS['manifest']


def _resource_for_app(check, app_id):
    for rid, name in check['list_resources']():
        if rid == app_id:
            return rid, name
    return None, None


def test_check_reports_in_sync_after_apply(applied):
    from app.services.drift_service import DriftService
    _project, _owner, api = applied
    check = _find_manifest_check()

    rid, name = _resource_for_app(check, api.id)
    assert rid == api.id, 'manifest-managed app should be listed'

    entry = DriftService.check_resource(check, rid, name)
    assert entry['status'] == 'in_sync', entry


def test_check_detects_drift(applied):
    from app import db
    from app.services.drift_service import DriftService
    _project, _owner, api = applied
    check = _find_manifest_check()

    # Mutate live state out from under the manifest.
    api.port = 9999
    db.session.commit()

    rid, name = _resource_for_app(check, api.id)
    entry = DriftService.check_resource(check, rid, name)
    assert entry['status'] == 'drifted', entry


def test_repair_reconverges(applied):
    from app import db
    from app.services.drift_service import DriftService
    _project, _owner, api = applied
    check = _find_manifest_check()
    app_id = api.id

    api.port = 9999
    db.session.commit()

    rid, name = _resource_for_app(check, app_id)
    assert DriftService.check_resource(check, rid, name)['status'] == 'drifted'

    result = DriftService.repair('manifest', app_id)
    assert result['success'] is True, result

    # re-list + re-check; live state should match the manifest again.
    rid, name = _resource_for_app(check, app_id)
    entry = DriftService.check_resource(check, rid, name)
    assert entry['status'] == 'in_sync', entry
