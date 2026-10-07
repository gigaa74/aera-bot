"""Owner-created paid links, reserved independently of the VPN panel."""

import sqlalchemy as sa

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "paid_links",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("client_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("link_encrypted", sa.Text, nullable=False),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("order_id", sa.String(36), sa.ForeignKey("sale_orders.id"), unique=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id")),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("duration_ms", sa.BigInteger),
        sa.Column("panel_email", sa.String(128)),
        *[
            sa.Column(name, sa.DateTime(timezone=True))
            for name in ("issued_at", "started_at", "expires_at", "checked_at")
        ],
    )


def downgrade():
    op.drop_table("paid_links")
