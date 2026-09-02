# ruff: noqa: I001

"""Fix Sina symbols for non-mainland market quotes."""

from alembic import op


revision = "0007_fix_market_quote_symbols"
down_revision = "0006_market_quote_configs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE market_quote_configs
        SET sina_symbol = CASE sina_symbol
            WHEN 'hstech' THEN 'hkHSTECH'
            WHEN 'xau' THEN 'hf_XAU'
            WHEN 'hf_BZ' THEN 'hf_OIL'
            ELSE sina_symbol
        END
        WHERE sina_symbol IN ('hstech', 'xau', 'hf_BZ')
        """
    )


def downgrade() -> None:
    op.execute(
        """
        UPDATE market_quote_configs
        SET sina_symbol = CASE sina_symbol
            WHEN 'hkHSTECH' THEN 'hstech'
            WHEN 'hf_XAU' THEN 'xau'
            WHEN 'hf_OIL' THEN 'hf_BZ'
            ELSE sina_symbol
        END
        WHERE sina_symbol IN ('hkHSTECH', 'hf_XAU', 'hf_OIL')
        """
    )
