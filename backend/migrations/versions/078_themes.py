"""Themes table (plan 60 — community themes platform).

Installed themes (imported, studio-authored, or pulled from the registry). A
theme is a validated map of CSS custom-property tokens — data, not code — so
the table is deliberately simple: no zips, no checksums, no permissions. The
bundled seed themes ship as JSON and are not rows unless explicitly imported.

Idempotent: guards on table presence like the other migrations here.

Revision ID: 078_themes
Revises: 077_linked_panel
Create Date: 2026-07-22
"""
from alembic import op
import sqlalchemy as sa

revision = '078_themes'
down_revision = '077_linked_panel'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'themes' in set(inspector.get_table_names()):
        return
    op.create_table(
        'themes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('author', sa.String(length=120), nullable=True),
        sa.Column('version', sa.String(length=32), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('base', sa.String(length=8), nullable=False, server_default='dark'),
        sa.Column('tokens', sa.JSON(), nullable=False),
        sa.Column('accent', sa.String(length=32), nullable=True),
        sa.Column('preview', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=16), nullable=False, server_default='import'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug'),
    )
    op.create_index('ix_themes_slug', 'themes', ['slug'], unique=True)


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    if 'themes' not in set(inspector.get_table_names()):
        return
    op.drop_index('ix_themes_slug', table_name='themes')
    op.drop_table('themes')
