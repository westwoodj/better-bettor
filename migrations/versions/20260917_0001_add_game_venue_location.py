"""Add structured venue location for MCP game context."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from nfl_data_aggregator.db.sa_models import Base

revision = "20260917_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("games"):
        Base.metadata.create_all(bind)
        return
    columns = {column["name"] for column in inspector.get_columns("games")}
    if "venue_location" not in columns:
        op.add_column("games", sa.Column("venue_location", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    if not inspector.has_table("games"):
        return
    columns = {column["name"] for column in inspector.get_columns("games")}
    if "venue_location" in columns:
        with op.batch_alter_table("games") as batch_op:
            batch_op.drop_column("venue_location")
