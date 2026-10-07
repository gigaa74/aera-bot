"""Remember when the current trial generation was verified as unused."""

import sqlalchemy as sa

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("trial_links", sa.Column("ready_at", sa.DateTime(timezone=True)))
    # Completed rotations were committed only after verifying unused two-day keys.
    op.execute("""UPDATE trial_links SET ready_at = checked_at
        WHERE user_id IS NULL AND issued_at IS NULL AND pending_uuid IS NULL
        AND (status = 'FREE' OR (status = 'UNAVAILABLE' AND client_uuid <> source_uuid))""")


def downgrade():
    op.drop_column("trial_links", "ready_at")
