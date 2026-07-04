"""Per-app resource limits (task #23).

Adds:
- applications.cpu_limit     (CPU cores, e.g. '1.5')
- applications.memory_limit  (e.g. '512m', '2g')

Both nullable — NULL means unlimited (today's behavior). When set they are
emitted into the app's generated compose service block (`cpus` / `mem_limit`).

Idempotent: MigrationService runs _fix_missing_columns() + db.create_all() on boot
before Alembic, so guard on the live schema.

Revision ID: 048_app_resource_limits
Revises: 047_agent_footprint_dirs
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = '048_app_resource_limits'
down_revision = '047_agent_footprint_dirs'
branch_labels = None
depends_on = None

_COLUMNS = ('cpu_limit', 'memory_limit')


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'applications' not in set(inspector.get_table_names()):
        return
    cols = {c['name'] for c in inspector.get_columns('applications')}
    for name in _COLUMNS:
        if name not in cols:
            op.add_column('applications', sa.Column(name, sa.String(16), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'applications' not in set(inspector.get_table_names()):
        return
    cols = {c['name'] for c in inspector.get_columns('applications')}
    for name in _COLUMNS:
        if name in cols:
            op.drop_column('applications', name)
