from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import Memo, MemoAttachment

MAX_MEMO_ATTACHMENTS = 12
MAX_MEMO_ATTACHMENT_SIZE = 20 * 1024 * 1024
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def validate_memo_files(text: str, files: Sequence[Any], existing_count: int = 0) -> None:
    if not text.strip() and not files:
        raise ValueError("正文或附件至少填写一项")
    if existing_count + len(files) > MAX_MEMO_ATTACHMENTS:
        raise ValueError(f"每条 Memo 最多上传 {MAX_MEMO_ATTACHMENTS} 个附件")
    for file in files:
        content_type = str(getattr(file, "content_type", "") or "").lower()
        if content_type.startswith("audio/"):
            raise ValueError("不支持音频附件")
        size = getattr(file, "size", None)
        if size is not None and size > MAX_MEMO_ATTACHMENT_SIZE:
            raise ValueError("附件不能超过 20 MB")
        if not getattr(file, "filename", None):
            raise ValueError("附件文件名不能为空")


def build_memo_view(memo: Memo, attachments: Sequence[MemoAttachment]) -> dict[str, Any]:
    return {
        "id": str(memo.id),
        "pinned": memo.pinned_at is not None,
        "text": memo.text,
        "source_type": "text",
        "version": memo.version,
        "created_at": memo.created_at.isoformat(),
        "updated_at": memo.updated_at.isoformat(),
        "attachments": [
            {
                "id": str(attachment.id),
                "file_name": attachment.file_name,
                "content_type": attachment.content_type,
                "size": attachment.size,
                "access_url": f"/api/memos/attachments/{attachment.id}",
                "created_at": attachment.created_at.isoformat(),
            }
            for attachment in attachments
        ],
    }


async def list_memos(
    db: AsyncSession,
    owner_username: str,
    query: str | None,
    page: int,
    page_size: int,
    date_from: date | None = None,
    date_to: date | None = None,
    pinned: bool | None = None,
) -> dict[str, Any]:
    conditions = [Memo.owner_username == owner_username, Memo.deleted_at.is_(None)]
    if pinned is True:
        conditions.append(Memo.pinned_at.is_not(None))
    elif pinned is False:
        conditions.append(Memo.pinned_at.is_(None))
    if date_from is not None:
        start = datetime.combine(date_from, time.min, SHANGHAI_TZ).astimezone(UTC)
        conditions.append(Memo.created_at >= start)
    if date_to is not None:
        end = datetime.combine(date_to + timedelta(days=1), time.min, SHANGHAI_TZ).astimezone(UTC)
        conditions.append(Memo.created_at < end)
    if query:
        pattern = f"%{query.strip()}%"
        conditions.append(
            or_(Memo.text.ilike(pattern), Memo.id.in_(
                select(MemoAttachment.memo_id).where(MemoAttachment.file_name.ilike(pattern))
            ))
        )
    total = int(await db.scalar(select(func.count()).select_from(Memo).where(*conditions)) or 0)
    rows = list(
        (
            await db.scalars(
                select(Memo)
                .options(selectinload(Memo.attachments))
                .where(*conditions)
                .order_by(Memo.pinned_at.desc().nulls_last(), Memo.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
    )
    return {
        "items": [build_memo_view(row, row.attachments) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }
