"""Add rule type to trading rules."""

from alembic import op


revision = "0010_trading_rule_type"
down_revision = "0009_trading_rule_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE trading_rules ADD COLUMN IF NOT EXISTS rule_type text NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trading_rules DROP COLUMN IF EXISTS rule_type")
