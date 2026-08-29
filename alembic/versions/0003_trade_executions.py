"""Add per-fill trade execution records."""

from alembic import op


revision = "0003_trade_executions"
down_revision = "0002_memos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE trade_executions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            trade_id uuid NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
            action varchar(8) NOT NULL,
            executed_at timestamptz NOT NULL,
            price numeric(30, 10) NOT NULL,
            quantity numeric(30, 10) NOT NULL,
            fee numeric(30, 10) NOT NULL DEFAULT 0,
            reason text NOT NULL,
            note text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX trade_executions_trade_time_idx ON trade_executions (trade_id, executed_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE trade_executions")
