"""Add configurable market quote sources."""
# ruff: noqa: I001

from alembic import op


revision = "0006_market_quote_configs"
down_revision = "0005_memo_pinning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE market_quote_configs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            display_name varchar(80) NOT NULL,
            market varchar(32) NOT NULL,
            sina_symbol varchar(80) NOT NULL,
            unit varchar(32) NOT NULL,
            sort_order integer NOT NULL DEFAULT 0,
            enabled boolean NOT NULL DEFAULT true,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX market_quote_configs_sina_symbol_uidx ON market_quote_configs (sina_symbol)"
    )
    op.execute(
        "CREATE INDEX market_quote_configs_enabled_sort_idx ON market_quote_configs (enabled, sort_order)"
    )
    op.execute(
        """
        INSERT INTO market_quote_configs
            (display_name, market, sina_symbol, unit, sort_order)
        VALUES
            ('上证指数', 'A股', 'sh000001', '点', 10),
            ('恒生指数', '港股', 'hkHSI', '点', 20),
            ('现货黄金', '贵金属', 'hf_XAU', '美元/盎司', 30),
            ('布伦特原油', '大宗商品', 'hf_BZ', '美元/桶', 40)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX market_quote_configs_enabled_sort_idx")
    op.execute("DROP INDEX market_quote_configs_sina_symbol_uidx")
    op.execute("DROP TABLE market_quote_configs")
