"""Manual subscription registry, one-use trial inventory and referral coupons."""

import sqlalchemy as sa

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def record():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table("trial_usage", sa.Column("fingerprint", sa.String(64), primary_key=True))
    op.create_table(
        "trial_links",
        *record(),
        sa.Column("label", sa.String(128), nullable=False),
        sa.Column("client_uuid", sa.String(36), nullable=False, unique=True),
        sa.Column("link_encrypted", sa.Text, nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), unique=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("panel_email", sa.String(128)),
        *[
            sa.Column(name, sa.DateTime(timezone=True))
            for name in ("issued_at", "started_at", "expires_at", "checked_at")
        ],
    )
    op.create_table(
        "manual_access",
        *record(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False, unique=True),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("link_encrypted", sa.Text),
    )
    op.create_table(
        "referral_coupons",
        *record(),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "referral_id", sa.String(36), sa.ForeignKey("referrals.id"), nullable=False, unique=True
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("reserved_ticket_id", sa.String(36), sa.ForeignKey("support_tickets.id")),
    )
    op.create_table(
        "sale_orders",
        *record(),
        sa.Column(
            "ticket_id",
            sa.String(36),
            sa.ForeignKey("support_tickets.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("plan_id", sa.String(36), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("coupon_id", sa.String(36), sa.ForeignKey("referral_coupons.id")),
        sa.Column("amount_rub_minor", sa.Integer, nullable=False),
        sa.Column("discount_percent", sa.Integer, nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True)),
        sa.Column("payment_id", sa.String(36), sa.ForeignKey("payments.id"), unique=True),
    )


def downgrade():
    for name in ("sale_orders", "referral_coupons", "manual_access", "trial_links", "trial_usage"):
        op.drop_table(name)
