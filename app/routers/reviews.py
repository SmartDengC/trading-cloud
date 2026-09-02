from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.database import get_db
from app.errors import ApiError
from app.models import ResearchReview
from app.schemas import ResearchReviewInput, ResearchReviewView, validate_review_slug
from app.security import current_session, require_origin
from app.trading_service import iso

router = APIRouter(prefix="/api/reviews", tags=["reviews"], dependencies=[Depends(current_session)])


def to_view(row: ResearchReview) -> ResearchReviewView:
    return ResearchReviewView(
        id=str(row.id),
        kind=cast(Literal["daily", "weekly"], row.kind),
        slug=row.slug,
        title=row.title,
        date_label=row.date_label,
        content=row.content,
        version=row.version,
        created_at=iso(row.created_at) or "",
        updated_at=iso(row.updated_at) or "",
    )


@router.get("", response_model=list[ResearchReviewView])
async def list_reviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    kind: Literal["daily", "weekly"] | None = None,
    date_from: Annotated[str | None, Query(alias="dateFrom")] = None,
    date_to: Annotated[str | None, Query(alias="dateTo")] = None,
    q: str | None = None,
) -> list[ResearchReviewView]:
    conditions: list[ColumnElement[bool]] = [ResearchReview.deleted_at.is_(None)]
    if kind:
        conditions.append(ResearchReview.kind == kind)
    if date_from:
        conditions.append(ResearchReview.date_label >= date_from)
    if date_to:
        conditions.append(ResearchReview.date_label <= date_to)
    if q:
        pattern = f"%{q}%"
        conditions.append(or_(ResearchReview.title.ilike(pattern), ResearchReview.content.ilike(pattern)))
    rows = list(
        (
            await db.scalars(
                select(ResearchReview).where(*conditions).order_by(ResearchReview.slug.desc())
            )
        ).all()
    )
    return [to_view(row) for row in rows]


@router.get("/{kind}/{slug}", response_model=ResearchReviewView)
async def get_review(
    kind: str, slug: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> ResearchReviewView:
    try:
        validate_review_slug(kind, slug)
    except ValueError as error:
        raise ApiError(400, str(error)) from error
    row = await db.scalar(
        select(ResearchReview).where(
            ResearchReview.kind == kind,
            ResearchReview.slug == slug,
            ResearchReview.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApiError(404, "未找到复盘内容")
    return to_view(row)


@router.put("/{kind}/{slug}", response_model=ResearchReviewView, dependencies=[Depends(require_origin)])
async def put_review(
    kind: str,
    slug: str,
    payload: ResearchReviewInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ResearchReviewView:
    try:
        validate_review_slug(kind, slug)
    except ValueError as error:
        raise ApiError(400, str(error)) from error
    existing = await db.scalar(
        select(ResearchReview).where(
            ResearchReview.kind == kind,
            ResearchReview.slug == slug,
            ResearchReview.deleted_at.is_(None),
        )
    )
    if existing:
        if payload.version is not None and payload.version != existing.version:
            raise ApiError(409, "版本冲突，请重新加载后再编辑")
        existing.title = payload.title
        existing.date_label = payload.date_label
        existing.content = payload.content
        existing.version += 1
        existing.updated_at = datetime.now(UTC)
        row = existing
    else:
        row = ResearchReview(
            kind=kind,
            slug=slug,
            title=payload.title,
            date_label=payload.date_label,
            content=payload.content,
        )
        db.add(row)
    await db.commit()
    await db.refresh(row)
    return to_view(row)


@router.delete("/{kind}/{slug}", dependencies=[Depends(require_origin)])
async def delete_review(
    kind: str, slug: str, db: Annotated[AsyncSession, Depends(get_db)]
) -> dict[str, bool]:
    try:
        validate_review_slug(kind, slug)
    except ValueError as error:
        raise ApiError(400, str(error)) from error
    result = await db.execute(
        update(ResearchReview)
        .where(
            ResearchReview.kind == kind,
            ResearchReview.slug == slug,
            ResearchReview.deleted_at.is_(None),
        )
        .values(deleted_at=datetime.now(UTC))
        .returning(ResearchReview.id)
    )
    if result.scalar_one_or_none() is None:
        await db.rollback()
        raise ApiError(404, "未找到复盘内容")
    await db.commit()
    return {"ok": True}
