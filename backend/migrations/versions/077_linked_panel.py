"""Linked-panel config table (ServerKit-to-ServerKit peering).

Single-row table holding the agent credentials this panel uses when it is
linked to a "master" ServerKit panel as a worker (embedded agent mode).

Idempotent: guards on table presence like other migrations here.

Revision ID: 077_linked_panel
Revises: 076_deployment_job_logs_sqlite_id
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = '077_linked_panel'
down_revision = '076_deployment_job_logs_sqlite_id'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'linked_panel_config' in set(inspector.get_table_names()):
        return
    op.create_table(
        'linked_panel_config',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('master_url', sa.String(length=255), nullable=False),
        sa.Column('agent_id', sa.String(length=64), nullable=False),
        sa.Column('api_key_prefix', sa.String(length=24), nullable=False),
        sa.Column('api_secret_encrypted', sa.Text(), nullable=False),
        sa.Column('remote_server_id', sa.String(length=36), nullable=False),
        sa.Column('remote_server_name', sa.String(length=120), nullable=True),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'linked_panel_config' in set(inspector.get_table_names()):
        op.drop_table('linked_panel_config')
