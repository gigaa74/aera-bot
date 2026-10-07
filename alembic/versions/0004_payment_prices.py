"""Explicit independent Stars and cryptocurrency prices."""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("plans", sa.Column("stars_price", sa.Integer(), nullable=True))
    op.add_column("plans", sa.Column("crypto_asset", sa.String(16), nullable=True))
    op.add_column("plans", sa.Column("crypto_amount", sa.String(80), nullable=True))


def downgrade():
    op.drop_column("plans", "crypto_amount")
    op.drop_column("plans", "crypto_asset")
    op.drop_column("plans", "stars_price")
