"""Declarative serverkit.yaml manifest persistence (plan 17, Phase 1).

Adds:
- applications.healthcheck_path (String(255), nullable) — populated from a
  manifest at import, editable in Settings, consumed by the restart gate.
- application_manifests table — one row per project storing the raw manifest,
  its normalized JSON, hash, provenance and status. Nothing detected is dropped.

Idempotent: MigrationService runs _fix_missing_columns() + db.create_all() on boot
before Alembic, so guard on the live schema.

Revision ID: 054_serverkit_manifest
Revises: 053_micro_cache
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = '054_serverkit_manifest'
down_revision = '053_micro_cache'
branch_labels = None
depends_on = None

_COLUMN = 'healthcheck_path'


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'applications' in tables:
        cols = {c['name'] for c in inspector.get_columns('applications')}
        if _COLUMN not in cols:
            op.add_column('applications', sa.Column(_COLUMN, sa.String(255), nullable=True))

    if 'application_manifests' not in tables:
        op.create_table(
            'application_manifests',
            sa.Column('id', sa.Integer, nullable=False),
            sa.Column('project_id', sa.Integer, nullable=False),
            sa.Column('raw_text', sa.Text, nullable=True),
            sa.Column('normalized_json', sa.Text, nullable=True),
            sa.Column('manifest_hash', sa.String(64), nullable=True),
            sa.Column('source_repo', sa.String(500), nullable=True),
            sa.Column('source_ref', sa.String(200), nullable=True),
            sa.Column('source_commit', sa.String(64), nullable=True),
            sa.Column('source_path', sa.String(255), nullable=True),
            sa.Column('status', sa.String(20), nullable=False, server_default='pending'),
            sa.Column('last_error', sa.Text, nullable=True),
            sa.Column('applied_at', sa.DateTime, nullable=True),
            sa.Column('created_at', sa.DateTime, nullable=True),
            sa.Column('updated_at', sa.DateTime, nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id']),
            sa.UniqueConstraint('project_id', name='uq_application_manifest_project'),
        )
        op.create_index('ix_application_manifests_project_id', 'application_manifests', ['project_id'])
        op.create_index('ix_application_manifests_manifest_hash', 'application_manifests', ['manifest_hash'])
        op.create_index('ix_application_manifests_status', 'application_manifests', ['status'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = set(inspector.get_table_names())

    if 'application_manifests' in tables:
        op.drop_table('application_manifests')

    if 'applications' in tables:
        cols = {c['name'] for c in inspector.get_columns('applications')}
        if _COLUMN in cols:
            op.drop_column('applications', _COLUMN)
