"""Add password hashes to users.

Revision ID: 0003
Revises: 94b2be811909
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "94b2be811909"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
