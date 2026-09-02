from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.errors import ApiError
from app.market_quotes import SinaQuoteClient, SinaQuoteError
from app.models import MarketQuoteConfig
from app.schemas import (
    MarketQuoteConfigInput,
    MarketQuoteConfigView,
    MarketQuoteItem,
    MarketQuotesView,
)
from app.security import current_session, require_origin

router = APIRouter(prefix="/api/market", tags=["market"], dependencies=[Depends(current_session)])
quote_client = SinaQuoteClient()


async def close_quote_client() -> None:
    await quote_client.close()


def config_view(row: MarketQuoteConfig) -> MarketQuoteConfigView:
    return MarketQuoteConfigView(
        id=str(row.id),
        display_name=row.display_name,
        market=row.market,
        sina_symbol=row.sina_symbol,
        unit=row.unit,
        sort_order=row.sort_order,
        enabled=row.enabled,
        version=row.version,
    )


async def load_config(db: AsyncSession, config_id: uuid.UUID) -> MarketQuoteConfig:
    row = await db.scalar(select(MarketQuoteConfig).where(MarketQuoteConfig.id == config_id))
    if row is None:
        raise ApiError(404, "未找到行情配置")
    return row


@router.get("/quote-configs", response_model=list[MarketQuoteConfigView])
async def list_quote_configs(db: Annotated[AsyncSession, Depends(get_db)]) -> list[MarketQuoteConfigView]:
    rows = (
        await db.scalars(
            select(MarketQuoteConfig).order_by(MarketQuoteConfig.sort_order, MarketQuoteConfig.created_at)
        )
    ).all()
    return [config_view(row) for row in rows]


@router.post("/quote-configs", response_model=MarketQuoteConfigView, dependencies=[Depends(require_origin)])
async def create_quote_config(
    payload: MarketQuoteConfigInput, db: Annotated[AsyncSession, Depends(get_db)]
) -> MarketQuoteConfigView:
    row = MarketQuoteConfig(**payload.model_dump(exclude={"version"}))
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ApiError(409, "新浪代码已存在") from error
    await db.refresh(row)
    return config_view(row)


@router.put(
    "/quote-configs/{config_id}", response_model=MarketQuoteConfigView, dependencies=[Depends(require_origin)]
)
async def update_quote_config(
    config_id: uuid.UUID, payload: MarketQuoteConfigInput, db: Annotated[AsyncSession, Depends(get_db)]
) -> MarketQuoteConfigView:
    row = await load_config(db, config_id)
    if payload.version is not None and payload.version != row.version:
        raise ApiError(409, "版本冲突，请重新加载后再编辑")
    for key, value in payload.model_dump(exclude={"version"}).items():
        setattr(row, key, value)
    row.version += 1
    row.updated_at = datetime.now(UTC)
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise ApiError(409, "新浪代码已存在") from error
    await db.refresh(row)
    return config_view(row)


@router.delete("/quote-configs/{config_id}", dependencies=[Depends(require_origin)])
async def disable_quote_config(
    config_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, bool]:
    row = await load_config(db, config_id)
    row.enabled = False
    row.version += 1
    row.updated_at = datetime.now(UTC)
    await db.commit()
    return {"ok": True}


@router.get("/quotes", response_model=MarketQuotesView)
async def get_quotes(db: Annotated[AsyncSession, Depends(get_db)]) -> MarketQuotesView:
    rows = list(
        (
            await db.scalars(
                select(MarketQuoteConfig)
                .where(MarketQuoteConfig.enabled)
                .order_by(MarketQuoteConfig.sort_order, MarketQuoteConfig.created_at)
            )
        ).all()
    )
    fetched_at = datetime.now(UTC)
    if not rows:
        return MarketQuotesView(items=[], fetched_at=fetched_at, source="新浪财经")
    symbols = [row.sina_symbol for row in rows]
    try:
        quotes = await quote_client.fetch(symbols)
    except SinaQuoteError as error:
        message = str(error)
        return MarketQuotesView(
            items=[
                MarketQuoteItem(
                    config_id=str(row.id),
                    display_name=row.display_name,
                    market=row.market,
                    sina_symbol=row.sina_symbol,
                    unit=row.unit,
                    status="error",
                    message=message,
                )
                for row in rows
            ],
            fetched_at=fetched_at,
            source="新浪财经",
        )
    items: list[MarketQuoteItem] = []
    for row in rows:
        quote = quotes.get(row.sina_symbol)
        items.append(
            MarketQuoteItem(
                config_id=str(row.id),
                display_name=row.display_name,
                market=row.market,
                sina_symbol=row.sina_symbol,
                unit=row.unit,
                value=quote.value if quote else None,
                change=quote.change if quote else None,
                change_percent=quote.change_percent if quote else None,
                quote_time=quote.quote_time if quote else None,
                status="ok" if quote else "error",
                message=None if quote else "行情数据不完整",
            )
        )
    return MarketQuotesView(items=items, fetched_at=fetched_at, source="新浪财经")
