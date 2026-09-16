"""Normalize legacy nullable trading rule text fields."""
# ruff: noqa: I001

from alembic import op


revision = "0011_normalize_trading_rule_text"
down_revision = "0010_trading_rule_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE trading_rules SET rule_type = '' WHERE rule_type IS NULL")
    op.execute("UPDATE trading_rules SET description = '' WHERE description IS NULL")
    op.execute("UPDATE trading_rules SET comment = '' WHERE comment IS NULL")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN rule_type SET DEFAULT ''")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN rule_type SET NOT NULL")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN description SET DEFAULT ''")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN description SET NOT NULL")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN comment SET DEFAULT ''")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN comment SET NOT NULL")


def downgrade() -> None:
    # Keep the columns populated when rolling back; only relax the constraints.
    op.execute("ALTER TABLE trading_rules ALTER COLUMN rule_type DROP NOT NULL")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN description DROP NOT NULL")
    op.execute("ALTER TABLE trading_rules ALTER COLUMN comment DROP NOT NULL")
