from __future__ import annotations

import uuid
from datetime import UTC, datetime
from math import ceil
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.errors import ApiError
from app.models import TradingRule
from app.schemas import TradingRuleInput, TradingRuleListView, TradingRuleView
from app.security import current_session, require_origin
from app.trading_service import iso

router = APIRouter(prefix="/api/trading", tags=["rules"], dependencies=[Depends(current_session)])


def to_view(row: TradingRule) -> TradingRuleView:
    return TradingRuleView(
        id=str(row.id),
        title=row.title,
        rule_type=row.rule_type or "",
        description=row.description or "",
        comment=row.comment or "",
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


@router.get("/rules", response_model=TradingRuleListView)
async def list_rules(
    db: Annotated[AsyncSession, Depends(get_db)],
    active: Annotated[bool | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    rule_type: Annotated[str | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=100)] = 10,
) -> TradingRuleListView:
    filters = []
    if active is not None:
        filters.append(TradingRule.active == active)
    if rule_type is not None and rule_type.strip():
        filters.append(TradingRule.rule_type == rule_type.strip())
    keyword = q.strip() if q else ""
    if keyword:
        pattern = f"%{keyword}%"
        filters.append(
            or_(
                TradingRule.title.ilike(pattern),
                TradingRule.description.ilike(pattern),
                TradingRule.comment.ilike(pattern),
            )
        )
    total = int((await db.scalar(select(func.count(TradingRule.id)).where(*filters))) or 0)
    query = (
        select(TradingRule)
        .where(*filters)
        .order_by(TradingRule.sort_order, TradingRule.created_at, TradingRule.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.scalars(query)).all()
    return TradingRuleListView(
        rules=[to_view(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
        total_pages=ceil(total / page_size) if total else 0,
    )


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
        rule_type=payload.rule_type,
        description=payload.description,
        comment=payload.comment,
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
    existing.rule_type = payload.rule_type
    existing.description = payload.description
    existing.comment = payload.comment
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
