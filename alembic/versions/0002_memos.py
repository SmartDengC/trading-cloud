"""Add Memo storage tables."""

from pathlib import Path

from alembic import op

revision = "0002_memos"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    path = Path(__file__).resolve().parents[2] / "sql" / "memory_schema.sql"
    connection = op.get_bind()
    for statement in path.read_text(encoding="utf-8").split(";"):
        statement = statement.strip()
        if statement:
            connection.exec_driver_sql(statement)


def downgrade() -> None:
    op.execute("DROP TABLE memo_attachments CASCADE")
    op.execute("DROP TABLE memos CASCADE")
