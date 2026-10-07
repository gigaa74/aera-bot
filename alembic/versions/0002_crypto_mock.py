"""Add isolated crypto simulation invoices and provider ledger."""

import sqlalchemy as sa

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def record_columns():
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def upgrade():
    op.create_table(
        "crypto_invoices",
        *record_columns(),
        sa.Column(
            "payment_id", sa.String(36), sa.ForeignKey("payments.id"), unique=True, nullable=False
        ),
        sa.Column("provider_invoice_id", sa.String(128), unique=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("expected_amount", sa.String(80), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    op.create_table(
        "crypto_mock_receipts",
        *record_columns(),
        sa.Column("provider_invoice_id", sa.String(128), unique=True, nullable=False),
        sa.Column("asset", sa.String(32), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("received_amount", sa.String(80), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("crypto_mock_receipts")
    op.drop_table("crypto_invoices")
