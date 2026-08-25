from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.errors import ApiError
from app.models import TradingRule
from app.schemas import TradingRuleInput, TradingRuleView
from app.security import current_session, require_origin
from app.trading_service import iso

router = APIRouter(prefix="/api/trading", tags=["rules"], dependencies=[Depends(current_session)])


def to_view(row: TradingRule) -> TradingRuleView:
    return TradingRuleView(
        id=str(row.id),
        title=row.title,
        description=row.description,
        sort_order=row.sort_order,
        active=row.active,
        version=row.version,
        created_at=iso(row.created_at) or "",
        updated_at=iso(row.updated_at) or "",
    )


async def load_rule(db: AsyncSession, rule_id: uuid.UUID) -> TradingRule:
    row = await db.scalar(select(TradingRule).where(TradingRule.id == rule_id))
    if row is None:
        raise ApiError(404, "未找到交易规则")
    return row


@router.get("/rules", response_model=list[TradingRuleView])
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    active: Annotated[bool | None, Query()] = None,
) -> list[TradingRuleView]:
    query = select(TradingRule).order_by(TradingRule.sort_order, TradingRule.created_at)
    if active is not None:
        query = query.where(TradingRule.active == active)
    rows = (await db.scalars(query)).all()
    return [to_view(row) for row in rows]


@router.get("/rules/{rule_id}", response_model=TradingRuleView)
async def get_rule(
    rule_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> TradingRuleView:
    return to_view(await load_rule(db, rule_id))


@router.post("/rules", response_model=TradingRuleView, dependencies=[Depends(require_origin)])
async def create_rule(
    payload: TradingRuleInput, db: Annotated[AsyncSession, Depends(get_db)]
) -> TradingRuleView:
    row = TradingRule(
        title=payload.title,
        description=payload.description,
        sort_order=payload.sort_order,
        active=payload.active,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return to_view(row)


@router.put("/rules/{rule_id}", response_model=TradingRuleView, dependencies=[Depends(require_origin)])
async def update_rule(
    rule_id: uuid.UUID,
    payload: TradingRuleInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TradingRuleView:
    existing = await load_rule(db, rule_id)
    if payload.version is not None and payload.version != existing.version:
        raise ApiError(409, "版本冲突，请重新加载后再编辑")
    existing.title = payload.title
    existing.description = payload.description
    existing.sort_order = payload.sort_order
    existing.active = payload.active
    existing.version += 1
    existing.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(existing)
    return to_view(existing)


@router.delete("/rules/{rule_id}", dependencies=[Depends(require_origin)])
async def delete_rule(
    rule_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, bool]:
    result = await db.execute(delete(TradingRule).where(TradingRule.id == rule_id).returning(TradingRule.id))
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise ApiError(404, "未找到交易规则")
    await db.commit()
    return {"ok": True}
