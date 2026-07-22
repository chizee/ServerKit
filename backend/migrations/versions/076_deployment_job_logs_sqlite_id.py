"""Fix ``deployment_job_logs.id`` autoincrement on SQLite.

SQLite only treats an exact ``INTEGER PRIMARY KEY`` as a rowid alias; the
``BIGINT PRIMARY KEY`` created for ``deployment_job_logs.id`` never
autoincrements, so the very first deployment-log insert on a fresh SQLite
install fails with ``NOT NULL constraint failed: deployment_job_logs.id`` and
the deployment job wedges at "running", step 0, with zero logs.

The model now uses ``BigInteger().with_variant(Integer, 'sqlite')``; this
migration rebuilds the table on existing SQLite databases. Other dialects
handle BIGINT autoincrement natively and are left untouched.

Idempotent: guards on dialect, table presence, and the live column type.

Revision ID: 076_deployment_job_logs_sqlite_id
Revises: 075_sandbox_runs
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = '076_deployment_job_logs_sqlite_id'
down_revision = '075_sandbox_runs'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    if conn.dialect.name != 'sqlite':
        return
    inspector = sa.inspect(conn)
    if 'deployment_job_logs' not in set(inspector.get_table_names()):
        return
    columns = {c['name']: c for c in inspector.get_columns('deployment_job_logs')}
    id_col = columns.get('id')
    if id_col is None or 'BIGINT' not in str(id_col['type']).upper():
        return
    # batch mode with recreate='always' rebuilds the table (the only way to
    # change a column type on SQLite) while preserving rows, indexes, and PK.
    with op.batch_alter_table('deployment_job_logs', recreate='always') as batch:
        batch.alter_column(
            'id',
            existing_type=sa.BigInteger(),
            type_=sa.Integer(),
            existing_nullable=False,
        )


def downgrade():
    # Harmless to keep the Integer PK; no-op on purpose.
    pass
