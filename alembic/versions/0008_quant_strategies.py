"""Add shared quantitative strategy snapshots and manual backtest records."""
# ruff: noqa: I001

from pathlib import Path

import sqlalchemy as sa
from alembic import op

from app.quant_seed_data import INITIAL_QUANT_STRATEGIES


revision = "0008_quant_strategies"
down_revision = "0007_fix_market_quote_symbols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE quant_strategies (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name varchar(120) NOT NULL,
            file_name varchar(255) NOT NULL,
            source_code text NOT NULL,
            timeframe varchar(40) NOT NULL,
            is_example boolean NOT NULL DEFAULT false,
            summary text NOT NULL DEFAULT '',
            explanation text NOT NULL,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE UNIQUE INDEX quant_strategies_name_uidx ON quant_strategies (name)")
    op.execute("CREATE UNIQUE INDEX quant_strategies_file_name_uidx ON quant_strategies (file_name)")
    op.execute(
        """
        CREATE TABLE quant_backtests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            strategy_id uuid NOT NULL REFERENCES quant_strategies(id) ON DELETE CASCADE,
            run_at timestamptz NOT NULL,
            timerange varchar(120) NOT NULL,
            pairs varchar(500) NOT NULL,
            timeframe varchar(40) NOT NULL,
            trade_count integer,
            total_return numeric(20, 8),
            win_rate numeric(10, 4),
            max_drawdown numeric(20, 8),
            profit_factor numeric(20, 8),
            notes text,
            version integer NOT NULL DEFAULT 1,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX quant_backtests_strategy_run_idx ON quant_backtests (strategy_id, run_at)")

    bind = op.get_bind()
    seed_query = sa.text(
        """
        INSERT INTO quant_strategies
            (name, file_name, source_code, timeframe, is_example, summary, explanation)
        VALUES
            (:name, :file_name, :source_code, :timeframe, :is_example, :summary, :explanation)
        ON CONFLICT (name) DO NOTHING
        """
    )
    for item in INITIAL_QUANT_STRATEGIES:
        bind.execute(
            seed_query,
            {
                "name": item.name,
                "file_name": item.file_name,
                "source_code": Path(item.source_path).read_text(encoding="utf-8"),
                "timeframe": item.timeframe,
                "is_example": item.is_example,
                "summary": item.summary,
                "explanation": item.explanation,
            },
        )


def downgrade() -> None:
    op.execute("DROP TABLE quant_backtests")
    op.execute("DROP INDEX quant_strategies_file_name_uidx")
    op.execute("DROP INDEX quant_strategies_name_uidx")
    op.execute("DROP TABLE quant_strategies")
