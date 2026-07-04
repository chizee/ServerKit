"""Manifest env references — value_from (plan 17, Phase 3).

Adds:
- environment_variables.value_from (Text, nullable) — a fromSecret/fromService/
  generate reference resolved at injection time (the value never lands in the
  row, so masking stays intact and a rotated secret propagates on next deploy).

Idempotent: MigrationService runs _fix_missing_columns() + db.create_all() on boot
before Alembic, so guard on the live schema.

Revision ID: 055_manifest_env_refs
Revises: 054_serverkit_manifest
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa

revision = '055_manifest_env_refs'
down_revision = '054_serverkit_manifest'
branch_labels = None
depends_on = None

_TABLE = 'environment_variables'
_COLUMN = 'value_from'


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if _TABLE not in set(inspector.get_table_names()):
        return
    cols = {c['name'] for c in inspector.get_columns(_TABLE)}
    if _COLUMN not in cols:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Text(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if _TABLE not in set(inspector.get_table_names()):
        return
    cols = {c['name'] for c in inspector.get_columns(_TABLE)}
    if _COLUMN in cols:
        op.drop_column(_TABLE, _COLUMN)
