"""Initial trading cloud schema.

Revision ID: 0001_initial
Revises:
"""

from pathlib import Path

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def execute_sql_file(path: Path) -> None:
    connection = op.get_bind()
    for statement in path.read_text(encoding="utf-8").split(";"):
        statement = statement.strip()
        if statement and statement not in {"BEGIN", "COMMIT"}:
            connection.exec_driver_sql(statement)


def upgrade() -> None:
    schema_path = Path(__file__).resolve().parents[2] / "sql" / "business_schema.sql"
    execute_sql_file(schema_path)
    execute_sql_file(schema_path.with_name("business_seed.sql"))


def downgrade() -> None:
    for table in (
        "auth_sessions",
        "import_batches",
        "trading_settings",
        "trade_attachments",
        "trade_error_tags",
        "trading_options",
        "daily_reviews",
        "trades",
        "research_reviews",
    ):
        op.execute(f'DROP TABLE "{table}" CASCADE')
