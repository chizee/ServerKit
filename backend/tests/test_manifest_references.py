"""Proving tests for Phase 3 — reference binders (plan 17)."""

import pytest

import app.models.application_manifest  # noqa: F401
from app.services.manifest_spec_service import ManifestSpecService
from app.services.manifest_apply_service import ManifestApplyService
from app.services.env_service import EnvService
from app.services.env_reference_service import EnvReferenceResolver


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
    proj = Project(workspace_id=ws.id, name='Ref', slug='ref')
    db.session.add(proj)
    db.session.commit()
    env = Environment(project_id=proj.id, name='Prod', slug='prod', is_default=True)
    db.session.add(env)
    db.session.commit()
    return proj


def _app_in(project, owner, name='api', port=8000):
    from app import db
    from app.models import Application
    a = Application(name=name, app_type='docker', port=port, user_id=owner.id,
                    project_id=project.id, status='running')
    db.session.add(a)
    db.session.commit()
    return a


def _secret(name, value):
    from app import db
    from app.models.secret_vault import SecretVault, Secret
    from app.utils.crypto import encrypt_secret
    vault = SecretVault.query.filter_by(slug='v').first()
    if not vault:
        vault = SecretVault(name='V', slug='v')
        db.session.add(vault)
        db.session.flush()
    s = Secret(vault_id=vault.id, name=name, encrypted_value=encrypt_secret(value))
    db.session.add(s)
    db.session.commit()
    return s


def test_from_secret_resolved_and_masked(project, owner):
    _secret('stripe_prod', 'sk_live_123')
    a = _app_in(project, owner)
    EnvService.set_env_reference(a.id, 'STRIPE_KEY', {'kind': 'secret', 'secret': 'stripe_prod'},
                                owner.id)
    # resolved at injection time
    env = EnvService.get_effective_env(a.id)
    assert env['STRIPE_KEY'] == 'sk_live_123'
    # masked + never serialized in the row
    rows = {r['key']: r for r in EnvService.get_env_vars(a.id, mask_secrets=True)}
    assert rows['STRIPE_KEY']['value'] == '••••••••'
    assert rows['STRIPE_KEY']['is_reference'] is True
    # even unmasked, the reference value is not stored in the row
    rows_unmasked = {r['key']: r for r in EnvService.get_env_vars(a.id)}
    assert rows_unmasked['STRIPE_KEY']['value'] == ''


def test_from_service_db_connection_string(project, owner):
    from app.services.managed_database_service import ManagedDatabaseService
    ManagedDatabaseService.record_provisioned(engine='postgresql', name='db',
                                              workspace_id=project.workspace_id)
    a = _app_in(project, owner)
    EnvService.set_env_reference(a.id, 'DATABASE_URL',
                                {'kind': 'service', 'service': 'db', 'property': 'connectionString'},
                                owner.id)
    env = EnvService.get_effective_env(a.id)
    assert env['DATABASE_URL'].startswith('postgresql://')
    assert 'db' in env['DATABASE_URL']


def test_from_service_app_url(project, owner):
    _app_in(project, owner, name='web', port=3000)
    a = _app_in(project, owner, name='worker')
    EnvService.set_env_reference(a.id, 'WEB_URL',
                                {'kind': 'service', 'service': 'web', 'property': 'url'}, owner.id)
    env = EnvService.get_effective_env(a.id)
    assert env['WEB_URL'] == 'http://web:3000'


def test_missing_secret_is_plan_time_issue(project, owner):
    manifest = {'version': 1, 'services': [{
        'name': 'api', 'type': 'web',
        'envVars': [{'key': 'MISSING', 'fromSecret': 'nope'}]}]}
    n = ManifestSpecService.normalize(manifest)
    plan = ManifestApplyService.plan(project, n)
    assert any(i['kind'] == 'missing_secret' and i['secret'] == 'nope' for i in plan['issues'])


def test_generate_creates_secret_and_is_idempotent(project, owner):
    from app.models.secret_vault import Secret
    manifest = {'version': 1, 'services': [{
        'name': 'api', 'type': 'web',
        'envVars': [{'key': 'SESSION_SECRET', 'generate': True}]}]}
    n = ManifestSpecService.normalize(manifest)

    result = ManifestApplyService.apply(project, n, user_id=owner.id)
    assert result['success'] is True

    from app.models import Application
    a = Application.query.filter_by(project_id=project.id, name='api').first()
    # a vault secret was generated and the env var references it
    env = EnvService.get_effective_env(a.id)
    assert env['SESSION_SECRET']  # non-empty generated value
    gen_secret = Secret.query.filter_by(name='api_session_secret').first()
    assert gen_secret is not None

    # idempotent — second plan does not regenerate
    plan2 = ManifestApplyService.plan(project, n)
    assert not any(s['type'] == 'set_env_ref' for s in plan2['steps'])


def test_apply_binds_from_secret_end_to_end(project, owner):
    _secret('api_token', 'tok-xyz')
    manifest = {'version': 1, 'services': [{
        'name': 'api', 'type': 'web',
        'envVars': [{'key': 'API_TOKEN', 'fromSecret': 'api_token'}]}]}
    n = ManifestSpecService.normalize(manifest)
    result = ManifestApplyService.apply(project, n, user_id=owner.id)
    assert result['success'] is True
    assert result['issues'] == []
    from app.models import Application
    a = Application.query.filter_by(project_id=project.id, name='api').first()
    assert EnvService.get_effective_env(a.id)['API_TOKEN'] == 'tok-xyz'
