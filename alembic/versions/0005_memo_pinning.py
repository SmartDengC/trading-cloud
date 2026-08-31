"""Add persistent Memo pinning."""

from alembic import op

revision = "0005_memo_pinning"
down_revision = "0004_backfill_trade_executions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE memos ADD COLUMN pinned_at timestamptz")
    op.execute(
        "CREATE INDEX memos_owner_pinned_idx ON memos (owner_username, pinned_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX memos_owner_pinned_idx")
    op.execute("ALTER TABLE memos DROP COLUMN pinned_at")
