from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.errors import ApiError
from app.models import QuantBacktest, QuantStrategy
from app.schemas import (
    QuantBacktestInput,
    QuantBacktestView,
    QuantStrategyInput,
    QuantStrategyListView,
    QuantStrategyView,
)
from app.security import current_session, require_origin
from app.trading_service import iso

router = APIRouter(prefix="/api/quant", tags=["quant"], dependencies=[Depends(current_session)])


def decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def backtest_view(row: QuantBacktest) -> QuantBacktestView:
    return QuantBacktestView(
        id=str(row.id),
        strategy_id=str(row.strategy_id),
        run_at=row.run_at,
        timerange=row.timerange,
        pairs=row.pairs,
        timeframe=row.timeframe,
        trade_count=row.trade_count,
        total_return=decimal_text(row.total_return),
        win_rate=decimal_text(row.win_rate),
        max_drawdown=decimal_text(row.max_drawdown),
        profit_factor=decimal_text(row.profit_factor),
        notes=row.notes,
        version=row.version,
        created_at=iso(row.created_at) or "",
        updated_at=iso(row.updated_at) or "",
    )


def strategy_list_view(row: QuantStrategy) -> QuantStrategyListView:
    latest = row.backtests[0] if row.backtests else None
    return QuantStrategyListView(
        id=str(row.id),
        name=row.name,
        file_name=row.file_name,
        timeframe=row.timeframe,
        is_example=row.is_example,
        summary=row.summary,
        latest_backtest=backtest_view(latest) if latest else None,
        version=row.version,
        created_at=iso(row.created_at) or "",
        updated_at=iso(row.updated_at) or "",
    )


def strategy_view(row: QuantStrategy) -> QuantStrategyView:
    return QuantStrategyView(
        **strategy_list_view(row).model_dump(),
        source_code=row.source_code,
        explanation=row.explanation,
        backtests=[backtest_view(item) for item in row.backtests],
    )


async def load_strategy(db: AsyncSession, strategy_id: uuid.UUID) -> QuantStrategy:
    row = await db.scalar(
        select(QuantStrategy)
        .options(selectinload(QuantStrategy.backtests))
        .where(QuantStrategy.id == strategy_id)
    )
    if row is None:
        raise ApiError(404, "未找到量化策略")
    return row


async def load_backtest(db: AsyncSession, backtest_id: uuid.UUID) -> QuantBacktest:
    row = await db.scalar(select(QuantBacktest).where(QuantBacktest.id == backtest_id))
    if row is None:
        raise ApiError(404, "未找到回测记录")
    return row


def apply_backtest(row: QuantBacktest, payload: QuantBacktestInput) -> None:
    row.run_at = payload.run_at
    row.timerange = payload.timerange
    row.pairs = payload.pairs
    row.timeframe = payload.timeframe
    row.trade_count = payload.trade_count
    row.total_return = Decimal(payload.total_return) if payload.total_return is not None else None
    row.win_rate = Decimal(payload.win_rate) if payload.win_rate is not None else None
    row.max_drawdown = Decimal(payload.max_drawdown) if payload.max_drawdown is not None else None
    row.profit_factor = Decimal(payload.profit_factor) if payload.profit_factor is not None else None
    row.notes = payload.notes


@router.get("/strategies", response_model=list[QuantStrategyListView])
async def list_strategies(
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = Query(default=None, max_length=120),
) -> list[QuantStrategyListView]:
    query = select(QuantStrategy).options(selectinload(QuantStrategy.backtests)).order_by(QuantStrategy.name)
    if q and q.strip():
        pattern = f"%{q.strip()}%"
        query = query.where(
            or_(
                QuantStrategy.name.ilike(pattern),
                QuantStrategy.file_name.ilike(pattern),
                QuantStrategy.summary.ilike(pattern),
            )
        )
    rows = (await db.scalars(query)).all()
    return [strategy_list_view(row) for row in rows]


@router.get("/strategies/{strategy_id}", response_model=QuantStrategyView)
async def get_strategy(
    strategy_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> QuantStrategyView:
    return strategy_view(await load_strategy(db, strategy_id))


@router.post("/strategies", response_model=QuantStrategyView, dependencies=[Depends(require_origin)])
async def create_strategy(
    payload: QuantStrategyInput, db: Annotated[AsyncSession, Depends(get_db)]
) -> QuantStrategyView:
    row = QuantStrategy(
        name=payload.name,
        file_name=payload.file_name,
        source_code=payload.source_code,
        timeframe=payload.timeframe,
        is_example=payload.is_example,
        summary=payload.summary,
        explanation=payload.explanation,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ApiError(409, "策略名称或文件名已存在") from error
    await db.refresh(row)
    row.backtests = []
    return strategy_view(row)


@router.put(
    "/strategies/{strategy_id}", response_model=QuantStrategyView, dependencies=[Depends(require_origin)]
)
async def update_strategy(
    strategy_id: uuid.UUID,
    payload: QuantStrategyInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuantStrategyView:
    row = await load_strategy(db, strategy_id)
    if payload.version is not None and payload.version != row.version:
        raise ApiError(409, "版本冲突，请重新加载后再编辑")
    row.name = payload.name
    row.file_name = payload.file_name
    row.source_code = payload.source_code
    row.timeframe = payload.timeframe
    row.is_example = payload.is_example
    row.summary = payload.summary
    row.explanation = payload.explanation
    row.version += 1
    row.updated_at = datetime.now(UTC)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ApiError(409, "策略名称或文件名已存在") from error
    await db.refresh(row)
    row.backtests = list(
        (
            await db.scalars(
                select(QuantBacktest)
                .where(QuantBacktest.strategy_id == row.id)
                .order_by(QuantBacktest.run_at.desc())
            )
        ).all()
    )
    return strategy_view(row)


@router.delete("/strategies/{strategy_id}", dependencies=[Depends(require_origin)])
async def delete_strategy(
    strategy_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, bool]:
    row = await load_strategy(db, strategy_id)
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post(
    "/strategies/{strategy_id}/backtests",
    response_model=QuantBacktestView,
    dependencies=[Depends(require_origin)],
)
async def create_backtest(
    strategy_id: uuid.UUID,
    payload: QuantBacktestInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuantBacktestView:
    await load_strategy(db, strategy_id)
    row = QuantBacktest(strategy_id=strategy_id)
    apply_backtest(row, payload)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return backtest_view(row)


@router.put(
    "/backtests/{backtest_id}", response_model=QuantBacktestView, dependencies=[Depends(require_origin)]
)
async def update_backtest(
    backtest_id: uuid.UUID,
    payload: QuantBacktestInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QuantBacktestView:
    row = await load_backtest(db, backtest_id)
    if payload.version is not None and payload.version != row.version:
        raise ApiError(409, "版本冲突，请重新加载后再编辑")
    apply_backtest(row, payload)
    row.version += 1
    row.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(row)
    return backtest_view(row)


@router.delete("/backtests/{backtest_id}", dependencies=[Depends(require_origin)])
async def delete_backtest(
    backtest_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, bool]:
    row = await load_backtest(db, backtest_id)
    await db.delete(row)
    await db.commit()
    return {"ok": True}
