"""Managed database users.

Adds the managed_database_users table: durable rows for users/grants ServerKit
creates on managed databases, including short-lived shadow credentials for
one-click admin SSO. Passwords are never stored.

Idempotent: MigrationService runs _fix_missing_columns() + db.create_all() on boot
before Alembic, so guard on the live schema.

Revision ID: 050_managed_database_users
Revises: 049_login_links
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa

revision = '050_managed_database_users'
down_revision = '049_login_links'
branch_labels = None
depends_on = None

TABLE = 'managed_database_users'


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE in set(inspector.get_table_names()):
        return
    op.create_table(
        TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('managed_database_id', sa.Integer(),
                  sa.ForeignKey('managed_databases.id', ondelete='CASCADE'),
                  nullable=False),
        sa.Column('username', sa.String(120), nullable=False),
        sa.Column('grants', sa.Text(), nullable=False, server_default='["ALL"]'),
        sa.Column('is_shadow', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.UniqueConstraint('managed_database_id', 'username',
                            name='uq_managed_db_user'),
    )
    op.create_index('ix_managed_database_users_managed_database_id',
                    TABLE, ['managed_database_id'])


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if TABLE not in set(inspector.get_table_names()):
        return
    op.drop_table(TABLE)
