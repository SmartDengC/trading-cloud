from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def to_camel(value: str) -> str:
    head, *tail = value.split("_")
    return head + "".join(part.capitalize() for part in tail)


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="forbid")


def _decimal(
    value: str | int | float | Decimal | None, label: str, *, optional: bool = False, zero: bool = False
) -> str | None:
    if value is None or value == "":
        if optional:
            return None
        raise ValueError(f"{label}不能为空")
    text = str(value).strip()
    if re.fullmatch(r"-?(?:\d+|\d*\.\d+)", text) is None:
        raise ValueError(f"{label}不合法")
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{label}不合法") from error
    if not number.is_finite() or (number < 0 if zero else number <= 0):
        raise ValueError(f"{label}必须{'大于等于' if zero else '大于'} 0")
    return format(number, "f")


class LoginInput(ApiModel):
    username: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=1, max_length=500)


class UserView(ApiModel):
    username: str
    role: Literal["user"] = "user"


class SessionView(ApiModel):
    logged_in: bool
    user: UserView | None = None


class ResearchReviewInput(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    date_label: str = Field(min_length=1, max_length=80)
    content: str = Field(min_length=1)
    version: int | None = Field(default=None, ge=1)

    @field_validator("title", "date_label", "content")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("content")
    @classmethod
    def content_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("Markdown 内容不能超过 2 MB")
        return value


class ResearchReviewView(ApiModel):
    id: str
    kind: Literal["daily", "weekly"]
    slug: str
    title: str
    date_label: str
    content: str
    version: int
    created_at: str
    updated_at: str


class MemoAttachmentView(ApiModel):
    id: str
    file_name: str
    content_type: str
    size: int
    access_url: str
    created_at: str


class MemoView(ApiModel):
    id: str
    text: str
    source_type: Literal["text"]
    version: int
    created_at: str
    updated_at: str
    attachments: list[MemoAttachmentView]


class MemoListView(ApiModel):
    items: list[MemoView]
    page: int
    page_size: int
    total: int
    has_more: bool


class MemoUpdate(ApiModel):
    text: str = Field(default="", max_length=100_000)
    version: int = Field(ge=1)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class TradingRuleInput(ApiModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=20000)
    sort_order: int = Field(default=0, ge=0, le=1_000_000)
    active: bool = True
    version: int | None = Field(default=None, ge=1)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("标题不能为空")
        return value


class TradingRuleView(ApiModel):
    id: str
    title: str
    description: str
    sort_order: int
    active: bool
    version: int
    created_at: str
    updated_at: str


class TradeInput(ApiModel):
    status: Literal["open", "closed"]
    trade_date: date
    instrument_code: str | None = Field(default=None, max_length=80)
    symbol: str = Field(min_length=1, max_length=160)
    market: Literal["crypto", "a_share"]
    side: Literal["long", "short"]
    strategy: str = Field(min_length=1, max_length=120)
    timeframe: str = Field(min_length=1, max_length=40)
    entry_at: datetime
    exit_at: datetime | None = None
    entry_reason: str = Field(min_length=1, max_length=10_000)
    exit_reason: str | None = Field(default=None, max_length=10_000)
    entry_price: str
    exit_price: str | None = None
    position_size: str
    position_basis: Literal["quantity", "notional"]
    settlement_currency: Literal["CNY", "USDT", "USD"]
    planned_risk_amount: str | None = None
    fees: str | None = "0"
    fx_to_cny: str
    execution_grade: Literal["A", "B", "C"] | None = None
    emotion: str | None = Field(default=None, max_length=80)
    error_tags: list[str] = Field(default_factory=list, max_length=10)
    error_notes: str | None = Field(default=None, max_length=10_000)
    did_well: str | None = Field(default=None, max_length=10_000)
    next_improvement: str | None = Field(default=None, max_length=10_000)
    version: int | None = Field(default=None, ge=1)

    @field_validator("symbol", "strategy", "timeframe", "entry_reason")
    @classmethod
    def required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("内容不能为空")
        return value

    @field_validator("entry_at", "exit_at")
    @classmethod
    def timezone_required(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("交易时间必须包含时区")
        return value.astimezone(UTC)

    @field_validator(
        "instrument_code", "exit_reason", "emotion", "error_notes", "did_well", "next_improvement"
    )
    @classmethod
    def optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("error_tags")
    @classmethod
    def unique_tags(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            value = value.strip()
            if not value or len(value) > 120:
                raise ValueError("错误标签不合法")
            if value not in result:
                result.append(value)
        return result[:10]

    @model_validator(mode="after")
    def validate_trade(self) -> TradeInput:
        self.entry_price = _decimal(self.entry_price, "开仓价") or ""
        self.position_size = _decimal(self.position_size, "仓位/名义金额") or ""
        self.fees = _decimal(self.fees, "手续费", zero=True) or "0"
        self.planned_risk_amount = _decimal(self.planned_risk_amount, "计划风险金额", optional=True)
        self.fx_to_cny = (
            "1" if self.settlement_currency == "CNY" else (_decimal(self.fx_to_cny, "人民币汇率") or "")
        )
        self.exit_price = _decimal(self.exit_price, "平仓价", optional=True)
        if self.status == "closed" and (
            self.exit_at is None or self.exit_price is None or not self.exit_reason
        ):
            raise ValueError("已平仓交易必须填写平仓时间、平仓价和出场理由")
        if self.exit_at is not None and self.exit_at < self.entry_at:
            raise ValueError("平仓时间不能早于开仓时间")
        if self.status == "open":
            self.exit_at = None
            self.exit_price = None
            self.exit_reason = None
        return self


class TradeAttachmentView(ApiModel):
    id: str
    trade_id: str
    file_name: str
    content_type: str
    size: int
    width: int | None
    height: int | None
    sort_order: int
    is_cover: bool
    file_url: str
    created_at: str


class TradeView(TradeInput):
    id: str
    gross_pnl: str | None
    net_pnl: str | None
    pnl_cny: str | None
    r_multiple: str | None
    hold_minutes: int | None
    is_winning: bool | None
    attachments: list[TradeAttachmentView]
    version: int
    created_at: str
    updated_at: str
    deleted_at: str | None


class TradeListView(ApiModel):
    trades: list[TradeView]
    total: int
    page: int
    page_size: int
    total_pages: int


class DashboardMetrics(ApiModel):
    closed_trades: int
    open_trades: int
    net_pnl_cny: str
    win_rate: float | None
    total_r: str | None
    average_pnl_cny: str | None
    grade_a_rate: float | None
    profit_factor: str | None


class DashboardBreakdown(ApiModel):
    label: str
    count: int
    pnl_cny: str
    win_rate: float | None


class DailyPnl(ApiModel):
    date: str
    pnl_cny: str
    count: int


class Distribution(ApiModel):
    label: str
    count: int


class TradingDashboard(ApiModel):
    metrics: DashboardMetrics
    daily_pnl: list[DailyPnl]
    by_market: list[DashboardBreakdown]
    by_strategy: list[DashboardBreakdown]
    grade_distribution: list[Distribution]
    emotion_distribution: list[Distribution]
    error_tag_distribution: list[Distribution]
    open_trades: list[TradeView]
    recent_trades: list[TradeView]
    pending_daily_reviews: list[str]


class DailyReviewInput(ApiModel):
    review_date: date | None = None
    market_plan: str | None = Field(default=None, max_length=10_000)
    daily_summary: str | None = Field(default=None, max_length=10_000)
    best_trade_id: str | None = Field(default=None, max_length=80)
    biggest_mistake: str | None = Field(default=None, max_length=10_000)
    tomorrow_one_thing: str | None = Field(default=None, max_length=10_000)
    planned_only: bool | None = None
    followed_stops: bool | None = None
    avoided_impulse_adds: bool | None = None
    avoided_revenge_trading: bool | None = None
    exited_as_planned: bool | None = None
    priority_fix: str | None = Field(default=None, max_length=10_000)
    notes: str | None = Field(default=None, max_length=10_000)
    version: int | None = Field(default=None, ge=1)

    @field_validator(
        "market_plan",
        "daily_summary",
        "best_trade_id",
        "biggest_mistake",
        "tomorrow_one_thing",
        "priority_fix",
        "notes",
    )
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        return value.strip() or None if value is not None else None

    @field_validator("best_trade_id")
    @classmethod
    def valid_best_trade_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            return str(uuid.UUID(value))
        except ValueError as error:
            raise ValueError("最佳交易 ID 不合法") from error


class DailyReviewView(DailyReviewInput):
    id: str
    review_date: date
    screenshot_complete: bool
    metrics: DashboardMetrics
    trades: list[TradeView]
    version: int
    created_at: str
    updated_at: str


class TradingOptionInput(ApiModel):
    kind: Literal["strategy", "timeframe", "emotion", "error_tag", "instrument_code", "symbol"]
    label: str = Field(min_length=1, max_length=120)
    active: bool
    sort_order: int


class TradingOptionView(TradingOptionInput):
    id: str


class TradingOptionUpdate(ApiModel):
    """按 id 更新单条选项的入参，所有字段可选（仅更新提供的字段）"""
    kind: Literal["strategy", "timeframe", "emotion", "error_tag", "instrument_code", "symbol"] | None = None
    label: str | None = Field(default=None, min_length=1, max_length=120)
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)


class TradingSettingsView(ApiModel):
    default_usdt_cny_rate: str


class TradingOptionsView(ApiModel):
    options: list[TradingOptionView]
    settings: TradingSettingsView


class TradingOptionsUpdate(ApiModel):
    options: list[TradingOptionInput] = Field(default_factory=list)
    default_usdt_cny_rate: str | None = None

    @field_validator("default_usdt_cny_rate")
    @classmethod
    def rate(cls, value: str | None) -> str | None:
        return _decimal(value, "默认汇率", optional=True)


class AttachmentUpdate(ApiModel):
    sort_order: int | None = Field(default=None, ge=0, le=1000)
    is_cover: bool | None = None


REVIEW_SLUGS = {"daily": re.compile(r"^\d{4}-\d{2}-\d{2}$"), "weekly": re.compile(r"^\d{4}-W\d{2}$")}


def validate_review_slug(kind: str, slug: str) -> None:
    if kind not in REVIEW_SLUGS or REVIEW_SLUGS[kind].fullmatch(slug) is None:
        raise ValueError("复盘类型或编号不合法")
