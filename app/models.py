from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResearchReview(TimestampMixin, Base):
    __tablename__ = "research_reviews"
    __table_args__ = (
        Index("research_reviews_kind_slug_uidx", "kind", "slug", unique=True),
        Index("research_reviews_kind_date_idx", "kind", "date_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    kind: Mapped[str] = mapped_column(String(8))
    slug: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(String(200))
    date_label: Mapped[str] = mapped_column(String(80))
    content: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Memo(TimestampMixin, Base):
    __tablename__ = "memos"
    __table_args__ = (Index("memos_owner_created_idx", "owner_username", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    owner_username: Mapped[str] = mapped_column(String(120))
    text: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(16), default="text", server_default="text")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attachments: Mapped[list[MemoAttachment]] = relationship(
        back_populates="memo", cascade="all, delete-orphan"
    )


class MemoAttachment(TimestampMixin, Base):
    __tablename__ = "memo_attachments"
    __table_args__ = (Index("memo_attachments_memo_idx", "memo_id", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    memo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("memos.id", ondelete="CASCADE")
    )
    object_key: Mapped[str] = mapped_column(Text, unique=True)
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(120))
    size: Mapped[int] = mapped_column(Integer)
    memo: Mapped[Memo] = relationship(back_populates="attachments")


class Trade(TimestampMixin, Base):
    __tablename__ = "trades"
    __table_args__ = (
        Index("trades_trade_date_idx", "trade_date"),
        Index("trades_market_idx", "market"),
        Index("trades_status_idx", "status"),
        Index("trades_source_row_uidx", "source_file_hash", "source_row", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    status: Mapped[str] = mapped_column(String(16))
    trade_date: Mapped[date] = mapped_column(Date)
    instrument_code: Mapped[str | None] = mapped_column(String(80))
    symbol: Mapped[str] = mapped_column(String(160))
    market: Mapped[str] = mapped_column(String(24))
    side: Mapped[str] = mapped_column(String(16))
    strategy: Mapped[str] = mapped_column(String(120))
    timeframe: Mapped[str] = mapped_column(String(40))
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    entry_reason: Mapped[str] = mapped_column(Text)
    exit_reason: Mapped[str | None] = mapped_column(Text)
    entry_price: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    position_size: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    position_basis: Mapped[str] = mapped_column(String(16))
    settlement_currency: Mapped[str] = mapped_column(String(12))
    planned_risk_amount: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    fees: Mapped[Decimal] = mapped_column(Numeric(30, 10), default=Decimal(0), server_default="0")
    fx_to_cny: Mapped[Decimal] = mapped_column(Numeric(30, 10))
    gross_pnl: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    net_pnl: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    pnl_cny: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    r_multiple: Mapped[Decimal | None] = mapped_column(Numeric(30, 10))
    hold_minutes: Mapped[int | None] = mapped_column(Integer)
    is_winning: Mapped[bool | None] = mapped_column(Boolean)
    execution_grade: Mapped[str | None] = mapped_column(String(4))
    emotion: Mapped[str | None] = mapped_column(String(80))
    error_notes: Mapped[str | None] = mapped_column(Text)
    did_well: Mapped[str | None] = mapped_column(Text)
    next_improvement: Mapped[str | None] = mapped_column(Text)
    source_file_hash: Mapped[str | None] = mapped_column(String(64))
    source_row: Mapped[int | None] = mapped_column(Integer)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class DailyReview(TimestampMixin, Base):
    __tablename__ = "daily_reviews"
    __table_args__ = (Index("daily_reviews_date_uidx", "review_date", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    review_date: Mapped[date] = mapped_column(Date)
    market_plan: Mapped[str | None] = mapped_column(Text)
    daily_summary: Mapped[str | None] = mapped_column(Text)
    best_trade_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trades.id", ondelete="SET NULL")
    )
    biggest_mistake: Mapped[str | None] = mapped_column(Text)
    tomorrow_one_thing: Mapped[str | None] = mapped_column(Text)
    planned_only: Mapped[bool | None] = mapped_column(Boolean)
    followed_stops: Mapped[bool | None] = mapped_column(Boolean)
    avoided_impulse_adds: Mapped[bool | None] = mapped_column(Boolean)
    avoided_revenge_trading: Mapped[bool | None] = mapped_column(Boolean)
    exited_as_planned: Mapped[bool | None] = mapped_column(Boolean)
    priority_fix: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


class TradingOption(TimestampMixin, Base):
    __tablename__ = "trading_options"
    __table_args__ = (Index("trading_options_kind_label_uidx", "kind", "label", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    kind: Mapped[str] = mapped_column(String(24))
    label: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")


class TradeErrorTag(Base):
    __tablename__ = "trade_error_tags"
    __table_args__ = (PrimaryKeyConstraint("trade_id", "option_id"),)

    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE")
    )
    option_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trading_options.id", ondelete="CASCADE")
    )


class TradeAttachment(TimestampMixin, Base):
    __tablename__ = "trade_attachments"
    __table_args__ = (
        Index("trade_attachments_trade_idx", "trade_id", "sort_order"),
        Index("trade_attachments_object_key_uidx", "object_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    trade_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trades.id", ondelete="CASCADE")
    )
    object_key: Mapped[str] = mapped_column(Text)
    file_name: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(80))
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_cover: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class TradingSetting(Base):
    __tablename__ = "trading_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImportBatch(Base):
    __tablename__ = "import_batches"
    __table_args__ = (Index("import_batches_source_uidx", "source_hash", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    source_hash: Mapped[str] = mapped_column(String(64))
    source_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(24))
    row_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    attachment_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    warnings: Mapped[list[str]] = mapped_column(JSONB, default=list, server_default="[]")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        Index("auth_sessions_token_hash_uidx", "token_hash", unique=True),
        Index("auth_sessions_expires_at_idx", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    token_hash: Mapped[str] = mapped_column(CHAR(64))
    username: Mapped[str] = mapped_column(String(120))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TradingRule(TimestampMixin, Base):
    __tablename__ = "trading_rules"
    __table_args__ = (
        Index("idx_trading_rules_sort_order", "sort_order"),
        Index("idx_trading_rules_active", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    title: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")


Index("trades_date_entry_idx", Trade.trade_date.desc(), Trade.entry_at.desc())
