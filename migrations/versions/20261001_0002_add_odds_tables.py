"""Add Odds API snapshot storage tables."""

from alembic import op
from sqlalchemy import inspect

from nfl_data_aggregator.db.sa_models import Base

revision = "20261001_0002"
down_revision = "20260917_0001"
branch_labels = None
depends_on = None

ODDS_TABLES = ("odds_events", "odds_snapshots", "odds_lines")


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in ODDS_TABLES]
    Base.metadata.create_all(bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    for name in reversed(ODDS_TABLES):
        if inspector.has_table(name):
            op.drop_table(name)
