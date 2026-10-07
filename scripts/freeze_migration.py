"""Developer utility: freeze current model DDL into initial Alembic migration."""

from pathlib import Path

from alembic.autogenerate import produce_migrations, render_python_code
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

from app.db.models import Base

engine = create_engine("sqlite://")
with engine.connect() as connection:
    migration = produce_migrations(MigrationContext.configure(connection), Base.metadata)
    upgrades = render_python_code(migration.upgrade_ops)
    downgrades = render_python_code(migration.downgrade_ops)
source = '''"""Initial frozen schema."""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
UPGRADES

def downgrade():
DOWNGRADES
'''.replace("UPGRADES", upgrades).replace("DOWNGRADES", downgrades)
Path("alembic/versions/0001_initial.py").write_text(source, encoding="utf-8")
