from __future__ import annotations

import math
import uuid
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any, Literal, cast

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.calculations import calculate_trade, decimal_string
from app.errors import ApiError
from app.models import (
    DailyReview,
    Trade,
    TradeAttachment,
    TradeErrorTag,
    TradingOption,
    TradingSetting,
)
from app.schemas import (
    DailyPnl,
    DailyReviewInput,
    DailyReviewView,
    DashboardBreakdown,
    DashboardMetrics,
    Distribution,
    TradeAttachmentView,
    TradeInput,
    TradeListView,
    TradeView,
    TradingDashboard,
    TradingOptionsUpdate,
    TradingOptionsView,
    TradingOptionView,
    TradingSettingsView,
)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def attachment_view(row: TradeAttachment) -> TradeAttachmentView:
    return TradeAttachmentView(
        id=str(row.id),
        trade_id=str(row.trade_id),
        file_name=row.file_name,
        content_type=row.content_type,
        size=row.size,
        width=row.width,
        height=row.height,
        sort_order=row.sort_order,
        is_cover=row.is_cover,
        file_url=f"/api/trading/files/{row.id}",
        created_at=iso(row.created_at) or "",
    )


def trade_view(row: Trade, attachments: list[TradeAttachment], error_tags: list[str]) -> TradeView:
    return TradeView(
        id=str(row.id),
        status=cast(Literal["open", "closed"], row.status),
        trade_date=row.trade_date,
        instrument_code=row.instrument_code,
        symbol=row.symbol,
        market=cast(Literal["crypto", "a_share"], row.market),
        side=cast(Literal["long", "short"], row.side),
        strategy=row.strategy,
        timeframe=row.timeframe,
        entry_at=row.entry_at,
        exit_at=row.exit_at,
        entry_reason=row.entry_reason,
        exit_reason=row.exit_reason,
        entry_price=decimal_string(row.entry_price) or "0",
        exit_price=decimal_string(row.exit_price),
        position_size=decimal_string(row.position_size) or "0",
        position_basis=cast(Literal["quantity", "notional"], row.position_basis),
        settlement_currency=cast(Literal["CNY", "USDT", "USD"], row.settlement_currency),
        planned_risk_amount=decimal_string(row.planned_risk_amount),
        fees=decimal_string(row.fees) or "0",
        fx_to_cny=decimal_string(row.fx_to_cny) or "1",
        gross_pnl=decimal_string(row.gross_pnl),
        net_pnl=decimal_string(row.net_pnl),
        pnl_cny=decimal_string(row.pnl_cny),
        r_multiple=decimal_string(row.r_multiple),
        hold_minutes=row.hold_minutes,
        is_winning=row.is_winning,
        execution_grade=cast(Literal["A", "B", "C"] | None, row.execution_grade),
        emotion=row.emotion,
        error_tags=error_tags,
        error_notes=row.error_notes,
        did_well=row.did_well,
        next_improvement=row.next_improvement,
        attachments=[attachment_view(item) for item in attachments],
        version=row.version,
        created_at=iso(row.created_at) or "",
        updated_at=iso(row.updated_at) or "",
        deleted_at=iso(row.deleted_at),
    )


async def hydrate_trades(db: AsyncSession, rows: list[Trade]) -> list[TradeView]:
    if not rows:
        return []
    ids = [row.id for row in rows]
    attachment_rows = list(
        (
            await db.scalars(
                select(TradeAttachment)
                .where(TradeAttachment.trade_id.in_(ids))
                .order_by(TradeAttachment.sort_order, TradeAttachment.created_at)
            )
        ).all()
    )
    tag_rows = (
        await db.execute(
            select(TradeErrorTag.trade_id, TradingOption.label)
            .join(TradingOption, TradingOption.id == TradeErrorTag.option_id)
            .where(TradeErrorTag.trade_id.in_(ids))
        )
    ).all()
    attachments: dict[uuid.UUID, list[TradeAttachment]] = defaultdict(list)
    tags: dict[uuid.UUID, list[str]] = defaultdict(list)
    for attachment in attachment_rows:
        attachments[attachment.trade_id].append(attachment)
    for trade_id, label in tag_rows:
        tags[trade_id].append(label)
    return [trade_view(row, attachments[row.id], tags[row.id]) for row in rows]


async def list_trades(
    db: AsyncSession,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    market: str | None = None,
    status: str | None = None,
    side: str | None = None,
    strategy: str | None = None,
    timeframe: str | None = None,
    grade: str | None = None,
    emotion: str | None = None,
    error_tag: str | None = None,
    query: str | None = None,
    outcome: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> TradeListView:
    conditions: list[Any] = [Trade.deleted_at.is_(None)]
    if from_date:
        conditions.append(Trade.trade_date >= from_date)
    if to_date:
        conditions.append(Trade.trade_date <= to_date)
    for column, value in (
        (Trade.market, market),
        (Trade.status, status),
        (Trade.side, side),
        (Trade.strategy, strategy),
        (Trade.timeframe, timeframe),
        (Trade.execution_grade, grade),
        (Trade.emotion, emotion),
    ):
        if value:
            conditions.append(column == value)
    if outcome in {"win", "loss"}:
        conditions.append(Trade.is_winning.is_(outcome == "win"))
    if query:
        pattern = f"%{query}%"
        conditions.append(or_(Trade.symbol.ilike(pattern), Trade.instrument_code.ilike(pattern)))
    if error_tag:
        tagged = (
            select(TradeErrorTag.trade_id)
            .join(TradingOption, TradingOption.id == TradeErrorTag.option_id)
            .where(TradingOption.label == error_tag)
        )
        conditions.append(Trade.id.in_(tagged))
    page = max(page, 1)
    page_size = min(max(page_size, 1), 500)
    total = int(await db.scalar(select(func.count()).select_from(Trade).where(*conditions)) or 0)
    rows = list(
        (
            await db.scalars(
                select(Trade)
                .where(*conditions)
                .order_by(Trade.trade_date.desc(), Trade.entry_at.desc())
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        ).all()
    )
    return TradeListView(
        trades=await hydrate_trades(db, rows),
        total=total,
        page=page,
        page_size=page_size,
        total_pages=math.ceil(total / page_size),
    )


async def get_trade(db: AsyncSession, trade_id: uuid.UUID) -> TradeView | None:
    row = await db.scalar(select(Trade).where(Trade.id == trade_id, Trade.deleted_at.is_(None)))
    if row is None:
        return None
    return (await hydrate_trades(db, [row]))[0]


def trade_values(input_data: TradeInput) -> dict[str, Any]:
    values: dict[str, Any] = {
        "status": input_data.status,
        "trade_date": input_data.trade_date,
        "instrument_code": input_data.instrument_code,
        "symbol": input_data.symbol,
        "market": input_data.market,
        "side": input_data.side,
        "strategy": input_data.strategy,
        "timeframe": input_data.timeframe,
        "entry_at": input_data.entry_at,
        "exit_at": input_data.exit_at,
        "entry_reason": input_data.entry_reason,
        "exit_reason": input_data.exit_reason,
        "entry_price": Decimal(input_data.entry_price),
        "exit_price": Decimal(input_data.exit_price) if input_data.exit_price else None,
        "position_size": Decimal(input_data.position_size),
        "position_basis": input_data.position_basis,
        "settlement_currency": input_data.settlement_currency,
        "planned_risk_amount": Decimal(input_data.planned_risk_amount)
        if input_data.planned_risk_amount
        else None,
        "fees": Decimal(input_data.fees or "0"),
        "fx_to_cny": Decimal(input_data.fx_to_cny),
        "execution_grade": input_data.execution_grade,
        "emotion": input_data.emotion,
        "error_notes": input_data.error_notes,
        "did_well": input_data.did_well,
        "next_improvement": input_data.next_improvement,
    }
    candidate = Trade(**values)
    calculation = calculate_trade(candidate)
    values.update(
        gross_pnl=calculation.gross_pnl,
        net_pnl=calculation.net_pnl,
        pnl_cny=calculation.pnl_cny,
        r_multiple=calculation.r_multiple,
        hold_minutes=calculation.hold_minutes,
        is_winning=calculation.is_winning,
    )
    return values


async def sync_error_tags(db: AsyncSession, trade_id: uuid.UUID, labels: list[str]) -> None:
    await db.execute(delete(TradeErrorTag).where(TradeErrorTag.trade_id == trade_id))
    if not labels:
        return
    for index, label in enumerate(labels):
        statement = (
            insert(TradingOption)
            .values(kind="error_tag", label=label, sort_order=index)
            .on_conflict_do_nothing(index_elements=[TradingOption.kind, TradingOption.label])
        )
        await db.execute(statement)
    option_rows = list(
        (
            await db.scalars(
                select(TradingOption).where(
                    TradingOption.kind == "error_tag", TradingOption.label.in_(labels)
                )
            )
        ).all()
    )
    db.add_all([TradeErrorTag(trade_id=trade_id, option_id=option.id) for option in option_rows])


async def create_trade(db: AsyncSession, input_data: TradeInput) -> TradeView:
    row = Trade(**trade_values(input_data))
    db.add(row)
    await db.flush()
    await sync_error_tags(db, row.id, input_data.error_tags)
    await db.commit()
    result = await get_trade(db, row.id)
    if result is None:
        raise ApiError(500, "创建交易失败")
    return result


async def update_trade(db: AsyncSession, trade_id: uuid.UUID, input_data: TradeInput) -> TradeView:
    if input_data.version is None:
        raise ApiError(400, "缺少版本号，请重新加载")
    exists = await db.scalar(select(Trade.id).where(Trade.id == trade_id, Trade.deleted_at.is_(None)))
    if exists is None:
        raise ApiError(404, "未找到交易记录")
    result = await db.execute(
        update(Trade)
        .where(Trade.id == trade_id, Trade.version == input_data.version, Trade.deleted_at.is_(None))
        .values(**trade_values(input_data), version=Trade.version + 1, updated_at=func.now())
        .returning(Trade.id)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise ApiError(409, "记录已在其他页面更新，请重新加载")
    await sync_error_tags(db, trade_id, input_data.error_tags)
    await db.commit()
    trade = await get_trade(db, trade_id)
    if trade is None:
        raise ApiError(404, "未找到交易记录")
    return trade


async def delete_trade(db: AsyncSession, trade_id: uuid.UUID, version: int | None) -> dict[str, str | bool]:
    if version is None or version <= 0:
        raise ApiError(400, "缺少或无效的版本号，请重新加载")
    result = await db.execute(
        update(Trade)
        .where(Trade.id == trade_id, Trade.version == version, Trade.deleted_at.is_(None))
        .values(deleted_at=func.now(), updated_at=func.now(), version=Trade.version + 1)
        .returning(Trade.id)
    )
    if result.scalar_one_or_none() is None:
        exists = await db.scalar(select(Trade.id).where(Trade.id == trade_id, Trade.deleted_at.is_(None)))
        await db.rollback()
        if exists is None:
            raise ApiError(404, "未找到交易记录")
        raise ApiError(409, "记录已在其他页面更新，请重新加载")
    await db.commit()
    return {"deleted": True, "id": str(trade_id)}


def aggregate_metrics(items: list[TradeView]) -> DashboardMetrics:
    closed = [item for item in items if item.status == "closed" and item.pnl_cny is not None]
    winners = [item for item in closed if item.is_winning]
    losses = [item for item in closed if item.net_pnl is not None and Decimal(item.net_pnl) < 0]
    net = sum((Decimal(item.pnl_cny or 0) for item in closed), Decimal(0))
    r_values = [Decimal(item.r_multiple) for item in closed if item.r_multiple is not None]
    total_r = sum(r_values, Decimal(0))
    gross_profit = sum((Decimal(item.pnl_cny or 0) for item in winners), Decimal(0))
    gross_loss = sum((abs(Decimal(item.pnl_cny or 0)) for item in losses), Decimal(0))
    graded = [item for item in closed if item.execution_grade]
    return DashboardMetrics(
        closed_trades=len(closed),
        open_trades=sum(item.status == "open" for item in items),
        net_pnl_cny=decimal_string(net.quantize(Decimal("0.01"))) or "0",
        win_rate=len(winners) / len(closed) if closed else None,
        total_r=decimal_string(total_r.quantize(Decimal("0.01"))) if r_values else None,
        average_pnl_cny=decimal_string((net / len(closed)).quantize(Decimal("0.01"))) if closed else None,
        grade_a_rate=sum(item.execution_grade == "A" for item in graded) / len(graded) if graded else None,
        profit_factor=decimal_string((gross_profit / gross_loss).quantize(Decimal("0.01")))
        if gross_loss > 0
        else None,
    )


def breakdown(
    items: list[TradeView], attribute: str, labels: dict[str, str] | None = None
) -> list[DashboardBreakdown]:
    groups: dict[str, list[TradeView]] = defaultdict(list)
    for item in items:
        if item.status != "closed":
            continue
        raw = getattr(item, attribute) or "未填写"
        groups[(labels or {}).get(raw, raw)].append(item)
    result = []
    for label, trades in groups.items():
        pnl = sum((Decimal(item.pnl_cny or 0) for item in trades), Decimal(0))
        result.append(
            DashboardBreakdown(
                label=label,
                count=len(trades),
                pnl_cny=decimal_string(pnl.quantize(Decimal("0.01"))) or "0",
                win_rate=sum(bool(item.is_winning) for item in trades) / len(trades),
            )
        )
    return sorted(result, key=lambda item: Decimal(item.pnl_cny), reverse=True)


async def dashboard(db: AsyncSession, from_date: date | None, to_date: date | None) -> TradingDashboard:
    result = await list_trades(db, from_date=from_date, to_date=to_date, page_size=500)
    items = result.trades
    daily: dict[str, tuple[Decimal, int]] = {}
    for item in items:
        if item.status != "closed":
            continue
        key = item.trade_date.isoformat()
        pnl, count = daily.get(key, (Decimal(0), 0))
        daily[key] = (pnl + Decimal(item.pnl_cny or 0), count + 1)
    dates = {item.trade_date for item in items}
    reviewed = set(
        (
            await db.scalars(
                select(DailyReview.review_date).where(
                    DailyReview.review_date.in_(dates), DailyReview.deleted_at.is_(None)
                )
            )
        ).all()
        if dates
        else []
    )
    grades = Counter(item.execution_grade for item in items if item.execution_grade)
    emotions = Counter(item.emotion for item in items if item.emotion)
    tags = Counter(tag for item in items for tag in item.error_tags)
    return TradingDashboard(
        metrics=aggregate_metrics(items),
        daily_pnl=[
            DailyPnl(date=key, pnl_cny=decimal_string(pnl.quantize(Decimal("0.01"))) or "0", count=count)
            for key, (pnl, count) in sorted(daily.items())
        ],
        by_market=breakdown(items, "market", {"crypto": "加密", "a_share": "A 股"}),
        by_strategy=breakdown(items, "strategy"),
        grade_distribution=[Distribution(label=key, count=count) for key, count in grades.most_common()],
        emotion_distribution=[Distribution(label=key, count=count) for key, count in emotions.most_common()],
        error_tag_distribution=[Distribution(label=key, count=count) for key, count in tags.most_common()],
        open_trades=[item for item in items if item.status == "open"][:10],
        recent_trades=items[:10],
        pending_daily_reviews=[item.isoformat() for item in sorted(dates - reviewed, reverse=True)[:14]],
    )


async def get_daily_review(db: AsyncSession, review_date: date) -> DailyReviewView:
    review = await db.scalar(
        select(DailyReview).where(DailyReview.review_date == review_date, DailyReview.deleted_at.is_(None))
    )
    trades = (await list_trades(db, from_date=review_date, to_date=review_date, page_size=250)).trades
    closed = [trade for trade in trades if trade.status == "closed"]
    now = datetime.now(UTC)
    return DailyReviewView(
        id=str(review.id) if review else "",
        review_date=review_date,
        market_plan=review.market_plan if review else None,
        daily_summary=review.daily_summary if review else None,
        best_trade_id=str(review.best_trade_id) if review and review.best_trade_id else None,
        biggest_mistake=review.biggest_mistake if review else None,
        tomorrow_one_thing=review.tomorrow_one_thing if review else None,
        planned_only=review.planned_only if review else None,
        followed_stops=review.followed_stops if review else None,
        avoided_impulse_adds=review.avoided_impulse_adds if review else None,
        avoided_revenge_trading=review.avoided_revenge_trading if review else None,
        exited_as_planned=review.exited_as_planned if review else None,
        priority_fix=review.priority_fix if review else None,
        notes=review.notes if review else None,
        screenshot_complete=bool(closed) and all(trade.attachments for trade in closed),
        metrics=aggregate_metrics(trades),
        trades=trades,
        version=review.version if review else 0,
        created_at=iso(review.created_at if review else now) or "",
        updated_at=iso(review.updated_at if review else now) or "",
    )


async def save_daily_review(
    db: AsyncSession, review_date: date, input_data: DailyReviewInput
) -> DailyReviewView:
    existing = await db.scalar(select(DailyReview).where(DailyReview.review_date == review_date))
    values = input_data.model_dump(exclude={"version", "review_date"})
    values["best_trade_id"] = uuid.UUID(input_data.best_trade_id) if input_data.best_trade_id else None
    values["deleted_at"] = None
    values["updated_at"] = func.now()
    if existing:
        if input_data.version is None:
            raise ApiError(400, "缺少版本号，请重新加载日复盘")
        result = await db.execute(
            update(DailyReview)
            .where(
                DailyReview.id == existing.id,
                DailyReview.version == input_data.version,
                DailyReview.deleted_at.is_(None),
            )
            .values(**values, version=DailyReview.version + 1)
            .returning(DailyReview.id)
        )
        if result.scalar_one_or_none() is None:
            await db.rollback()
            raise ApiError(409, "日复盘已在其他页面更新，请重新加载")
    else:
        db.add(DailyReview(review_date=review_date, **values))
    await db.commit()
    return await get_daily_review(db, review_date)


async def get_options(db: AsyncSession) -> TradingOptionsView:
    options = list(
        (
            await db.scalars(
                select(TradingOption).order_by(
                    TradingOption.kind, TradingOption.sort_order, TradingOption.label
                )
            )
        ).all()
    )
    rate = await db.scalar(select(TradingSetting.value).where(TradingSetting.key == "default_usdt_cny_rate"))
    return TradingOptionsView(
        options=[
            TradingOptionView(
                id=str(option.id),
                kind=cast(
                    Literal[
                        "strategy",
                        "timeframe",
                        "emotion",
                        "error_tag",
                        "instrument_code",
                        "symbol",
                    ],
                    option.kind,
                ),
                label=option.label,
                active=option.active,
                sort_order=option.sort_order,
            )
            for option in options
        ],
        settings=TradingSettingsView(default_usdt_cny_rate=rate or "7.2"),
    )


async def update_options(db: AsyncSession, payload: TradingOptionsUpdate) -> TradingOptionsView:
    for option in payload.options:
        values = option.model_dump()
        statement = (
            insert(TradingOption)
            .values(**values)
            .on_conflict_do_update(
                index_elements=[TradingOption.kind, TradingOption.label],
                set_={"active": option.active, "sort_order": option.sort_order, "updated_at": func.now()},
            )
        )
        await db.execute(statement)
    if payload.default_usdt_cny_rate:
        statement = (
            insert(TradingSetting)
            .values(key="default_usdt_cny_rate", value=payload.default_usdt_cny_rate)
            .on_conflict_do_update(
                index_elements=[TradingSetting.key],
                set_={"value": payload.default_usdt_cny_rate, "updated_at": func.now()},
            )
        )
        await db.execute(statement)
    await db.commit()
    return await get_options(db)


async def delete_option(db: AsyncSession, option_id: uuid.UUID) -> TradingOptionsView:
    result = await db.execute(delete(TradingOption).where(TradingOption.id == option_id))
    if result.rowcount == 0:
        await db.rollback()
        raise ApiError(404, "未找到录入字段")
    await db.commit()
    return await get_options(db)
