"""Record explicit acceptance of purchase terms."""

import sqlalchemy as sa

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "users", sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("users", sa.Column("terms_version", sa.String(64), nullable=True))


def downgrade():
    op.drop_column("users", "terms_version")
    op.drop_column("users", "terms_accepted_at")
