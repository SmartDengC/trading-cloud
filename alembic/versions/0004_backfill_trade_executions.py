"""Backfill legacy trades into per-execution records."""

from alembic import op


revision = "0004_backfill_trade_executions"
down_revision = "0003_trade_executions"
branch_labels = None
depends_on = None


ENTRY_NOTE = "由旧 trades.entry_* 字段迁移"
EXIT_NOTE = "由旧 trades.exit_* 字段迁移"


def upgrade() -> None:
    # Each legacy trade has at most one entry row. The guard makes this safe
    # to rerun after a partially completed manual migration.
    op.execute(
        f"""
        INSERT INTO trade_executions (
            trade_id,
            action,
            executed_at,
            price,
            quantity,
            fee,
            reason,
            note
        )
        SELECT
            t.id,
            'entry',
            t.entry_at,
            t.entry_price,
            t.position_size,
            0,
            t.entry_reason,
            '{ENTRY_NOTE}'
        FROM trades t
        WHERE NOT EXISTS (
            SELECT 1
            FROM trade_executions e
            WHERE e.trade_id = t.id
              AND e.action = 'entry'
        )
        """
    )

    # Legacy fees are kept on the exit row because they describe the whole
    # completed trade and there is no per-fill fee split in the old schema.
    op.execute(
        f"""
        INSERT INTO trade_executions (
            trade_id,
            action,
            executed_at,
            price,
            quantity,
            fee,
            reason,
            note
        )
        SELECT
            t.id,
            'exit',
            t.exit_at,
            t.exit_price,
            t.position_size,
            t.fees,
            COALESCE(t.exit_reason, '旧记录未填写平仓理由'),
            '{EXIT_NOTE}'
        FROM trades t
        WHERE t.exit_at IS NOT NULL
          AND t.exit_price IS NOT NULL
          AND NOT EXISTS (
              SELECT 1
              FROM trade_executions e
              WHERE e.trade_id = t.id
                AND e.action = 'exit'
          )
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DELETE FROM trade_executions
        WHERE note IN ('{ENTRY_NOTE}', '{EXIT_NOTE}')
        """
    )
