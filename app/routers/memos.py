from __future__ import annotations

import uuid
from collections.abc import Iterator
from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.errors import ApiError
from app.memo_service import (
    MAX_MEMO_ATTACHMENT_SIZE,
    build_memo_view,
    list_memos,
    validate_memo_files,
)
from app.models import AuthSession, Memo, MemoAttachment
from app.schemas import MemoListView, MemoUpdate, MemoView
from app.security import current_session, require_origin
from app.storage import get_minio, is_minio_error

router = APIRouter(prefix="/api/memos", tags=["memos"], dependencies=[Depends(current_session)])


def _owner(session: AuthSession) -> str:
    return session.username


@router.get("", response_model=MemoListView)
async def memos_index(
    session: Annotated[AuthSession, Depends(current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, alias="pageSize", ge=1, le=50),
) -> dict[str, object]:
    return await list_memos(db, _owner(session), q, page, page_size)


@router.get("/attachments/{attachment_id}")
async def memo_attachment(
    attachment_id: uuid.UUID,
    session: Annotated[AuthSession, Depends(current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    row = await db.scalar(
        select(MemoAttachment)
        .join(Memo)
        .where(
            MemoAttachment.id == attachment_id,
            Memo.owner_username == _owner(session),
            Memo.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApiError(404, "未找到附件")
    try:
        stream = await run_in_threadpool(get_minio().get_object, _settings_bucket(), row.object_key)
    except Exception as error:
        if is_minio_error(error):
            raise ApiError(404, "未找到附件文件") from error
        raise

    def chunks() -> Iterator[bytes]:
        try:
            yield from stream.stream(64 * 1024)
        finally:
            stream.close()
            stream.release_conn()

    return StreamingResponse(
        chunks(),
        media_type=row.content_type,
        headers={
            "Content-Disposition": f"inline; filename*=UTF-8''{quote(row.file_name)}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/{memo_id}", response_model=MemoView)
async def memo_get(
    memo_id: uuid.UUID,
    session: Annotated[AuthSession, Depends(current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    row = await db.scalar(
        select(Memo)
        .options(selectinload(Memo.attachments))
        .where(Memo.id == memo_id, Memo.owner_username == _owner(session), Memo.deleted_at.is_(None))
    )
    if row is None:
        raise ApiError(404, "未找到 Memo")
    return build_memo_view(row, row.attachments)


@router.post("", response_model=MemoView, dependencies=[Depends(require_origin)])
async def memo_create(
    session: Annotated[AuthSession, Depends(current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    text: Annotated[str, Form()] = "",
    files: Annotated[list[UploadFile] | None, File()] = None,
) -> dict[str, object]:
    uploads = files or []
    validate_memo_files(text, uploads)
    payloads: list[tuple[UploadFile, bytes]] = []
    for file in uploads:
        data = await file.read(MAX_MEMO_ATTACHMENT_SIZE + 1)
        if len(data) > MAX_MEMO_ATTACHMENT_SIZE:
            raise ApiError(400, "附件不能超过 20 MB")
        file.size = len(data)
        payloads.append((file, data))

    row = Memo(owner_username=_owner(session), text=text.strip(), source_type="text")
    db.add(row)
    object_keys: list[str] = []
    try:
        await db.flush()
        for file, data in payloads:
            content_type = (file.content_type or "application/octet-stream").lower()
            object_key = f"memos/{row.id}/{uuid.uuid4()}"
            await run_in_threadpool(
                get_minio().put_object,
                _settings_bucket(),
                object_key,
                BytesIO(data),
                len(data),
                content_type=content_type,
            )
            object_keys.append(object_key)
            db.add(
                MemoAttachment(
                    memo_id=row.id,
                    object_key=object_key,
                    file_name=(file.filename or "attachment")[:255],
                    content_type=content_type,
                    size=len(data),
                )
            )
        await db.commit()
    except Exception:
        await db.rollback()
        for object_key in object_keys:
            await _remove_object(object_key)
        raise

    saved = await db.scalar(
        select(Memo).options(selectinload(Memo.attachments)).where(Memo.id == row.id)
    )
    assert saved is not None
    return build_memo_view(saved, saved.attachments)


@router.patch("/{memo_id}", response_model=MemoView, dependencies=[Depends(require_origin)])
async def memo_update(
    memo_id: uuid.UUID,
    payload: MemoUpdate,
    session: Annotated[AuthSession, Depends(current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, object]:
    row = await db.scalar(
        select(Memo)
        .options(selectinload(Memo.attachments))
        .where(
            Memo.id == memo_id,
            Memo.owner_username == _owner(session),
            Memo.deleted_at.is_(None),
        )
    )
    if row is None:
        raise ApiError(404, "未找到 Memo")
    if row.version != payload.version:
        raise ApiError(409, "Memo 已被修改，请重新加载")
    if not payload.text.strip() and not row.attachments:
        raise ApiError(400, "正文或附件至少填写一项")
    row.text = payload.text
    row.version += 1
    await db.commit()
    updated = await db.scalar(
        select(Memo).options(selectinload(Memo.attachments)).where(Memo.id == row.id)
    )
    assert updated is not None
    return build_memo_view(updated, updated.attachments)


@router.delete("/{memo_id}", dependencies=[Depends(require_origin)])
async def memo_delete(
    memo_id: uuid.UUID,
    session: Annotated[AuthSession, Depends(current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, bool]:
    row = await db.scalar(
        select(Memo).options(selectinload(Memo.attachments)).where(
            Memo.id == memo_id, Memo.owner_username == _owner(session), Memo.deleted_at.is_(None)
        )
    )
    if row is None:
        raise ApiError(404, "未找到 Memo")
    await db.delete(row)
    await db.commit()
    for attachment in row.attachments:
        await _remove_object(attachment.object_key)
    return {"ok": True}


def _settings_bucket() -> str:
    from app.config import get_settings

    return get_settings().minio_bucket


async def _remove_object(object_key: str) -> None:
    try:
        await run_in_threadpool(get_minio().remove_object, _settings_bucket(), object_key)
    except Exception as error:
        if not is_minio_error(error):
            raise
