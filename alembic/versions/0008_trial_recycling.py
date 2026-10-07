"""Durable trial key rotation and anonymous activation counters."""

import sqlalchemy as sa

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("trial_links") as batch:
        batch.add_column(sa.Column("source_uuid", sa.String(36)))
        batch.add_column(sa.Column("pending_uuid", sa.String(36)))
        batch.add_column(sa.Column("recycle_reason", sa.String(32)))
        batch.add_column(
            sa.Column("baseline_bytes", sa.BigInteger(), nullable=False, server_default="0")
        )
        batch.add_column(sa.Column("activation_deadline_ms", sa.BigInteger()))
        batch.create_unique_constraint("uq_trial_source_uuid", ["source_uuid"])
    op.execute("UPDATE trial_links SET source_uuid = client_uuid")
    op.add_column("trial_usage", sa.Column("activated_at", sa.DateTime(timezone=True)))


def downgrade():
    op.drop_column("trial_usage", "activated_at")
    with op.batch_alter_table("trial_links") as batch:
        batch.drop_constraint("uq_trial_source_uuid", type_="unique")
        for field in (
            "source_uuid",
            "pending_uuid",
            "recycle_reason",
            "baseline_bytes",
            "activation_deadline_ms",
        ):
            batch.drop_column(field)
