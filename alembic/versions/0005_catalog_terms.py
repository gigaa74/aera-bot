"""Calendar billing and explicit unlimited devices; preserve existing subscriptions."""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("plans", sa.Column("duration_months", sa.Integer(), nullable=True))
    for table in ["plans", "subscriptions"]:
        op.add_column(
            table,
            sa.Column("unlimited_devices", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    for table in ["subscriptions", "plans"]:
        op.drop_column(table, "unlimited_devices")
    op.drop_column("plans", "duration_months")
