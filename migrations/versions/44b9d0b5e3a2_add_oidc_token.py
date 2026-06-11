"""Add oidc_token to user table

Revision ID: 44b9d0b5e3a2
Revises: 
Create Date: 2026-06-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '44b9d0b5e3a2'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Use batch_alter_table for SQLite compatibility across all supported DBs
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('oidc_token', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('oidc_token')
