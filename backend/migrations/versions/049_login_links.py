"""One-time login links.

Adds the login_links table: single-use, short-TTL, optionally IP-bound
login URLs minted by an admin. Only the SHA-256 token hash is stored.

Idempotent: MigrationService runs _fix_missing_columns() + db.create_all() on boot
before Alembic, so guard on the live schema.

Revision ID: 049_login_links
Revises: 048_app_resource_limits
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = '049_login_links'
down_revision = '048_app_resource_limits'
branch_labels = None
depends_on = None

TABLE = 'login_links'


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE in set(inspector.get_table_names()):
        return
    op.create_table(
        TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('user_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('created_by_id', sa.Integer(),
                  sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=False),
        sa.Column('used_at', sa.DateTime(), nullable=True),
        sa.Column('bound_ip', sa.String(64), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_login_links_token_hash', TABLE, ['token_hash'], unique=True)
    op.create_index('ix_login_links_user_id', TABLE, ['user_id'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in set(inspector.get_table_names()):
        return
    op.drop_table(TABLE)
