"""Ensure trading rules storage exists and supports comments."""
# ruff: noqa: I001

from alembic import op


revision = "0009_trading_rule_comments"
down_revision = "0008_quant_strategies"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS trading_rules (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            title text NOT NULL,
            description text NOT NULL DEFAULT '',
            sort_order integer NOT NULL DEFAULT 0,
            active boolean NOT NULL DEFAULT true,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_trading_rules_sort_order ON trading_rules (sort_order)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_trading_rules_active ON trading_rules (active)")
    op.execute(
        "ALTER TABLE trading_rules ADD COLUMN IF NOT EXISTS comment text NOT NULL DEFAULT ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE trading_rules DROP COLUMN IF EXISTS comment")
