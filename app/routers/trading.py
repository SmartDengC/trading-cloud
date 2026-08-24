from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response, StreamingResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.errors import ApiError
from app.exporter import create_export
from app.models import Trade, TradeAttachment
from app.schemas import (
    AttachmentUpdate,
    DailyReviewInput,
    DailyReviewView,
    TradeAttachmentView,
    TradeInput,
    TradeListView,
    TradeView,
    TradingDashboard,
    TradingOptionsUpdate,
    TradingOptionsView,
)
from app.security import current_session, require_origin
from app.storage import get_minio, is_minio_error
from app.trading_service import (
    attachment_view,
    create_trade,
    dashboard,
    delete_trade,
    get_daily_review,
    get_options,
    get_trade,
    list_trades,
    save_daily_review,
    update_options,
    update_trade,
)

router = APIRouter(prefix="/api/trading", tags=["trading"], dependencies=[Depends(current_session)])


@router.get("/trades", response_model=TradeListView)
async def trades_index(
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
    market: str | None = None,
    status: str | None = None,
    side: str | None = None,
    strategy: str | None = None,
    timeframe: str | None = None,
    grade: str | None = None,
    emotion: str | None = None,
    error_tag: Annotated[str | None, Query(alias="errorTag")] = None,
    q: str | None = None,
    outcome: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=500)] = 50,
) -> TradeListView:
    return await list_trades(
        db,
        from_date=from_date,
        to_date=to_date,
        market=market,
        status=status,
        side=side,
        strategy=strategy,
        timeframe=timeframe,
        grade=grade,
        emotion=emotion,
        error_tag=error_tag,
        query=q,
        outcome=outcome,
        page=page,
        page_size=page_size,
    )


@router.post("/trades", response_model=TradeView, dependencies=[Depends(require_origin)])
async def trades_create(payload: TradeInput, db: Annotated[AsyncSession, Depends(get_db)]) -> TradeView:
    return await create_trade(db, payload)


@router.get("/trades/{trade_id}", response_model=TradeView)
async def trades_get(trade_id: uuid.UUID, db: Annotated[AsyncSession, Depends(get_db)]) -> TradeView:
    trade = await get_trade(db, trade_id)
    if trade is None:
        raise ApiError(404, "未找到交易记录")
    return trade


@router.patch("/trades/{trade_id}", response_model=TradeView, dependencies=[Depends(require_origin)])
async def trades_update(
    trade_id: uuid.UUID, payload: TradeInput, db: Annotated[AsyncSession, Depends(get_db)]
) -> TradeView:
    return await update_trade(db, trade_id, payload)


@router.delete("/trades/{trade_id}", dependencies=[Depends(require_origin)])
async def trades_delete(
    trade_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    version: int | None = None,
) -> dict[str, str | bool]:
    return await delete_trade(db, trade_id, version)


@router.get("/dashboard", response_model=TradingDashboard)
async def trading_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> TradingDashboard:
    return await dashboard(db, from_date, to_date)


@router.get("/daily-reviews/{review_date}", response_model=DailyReviewView)
async def daily_get(review_date: date, db: Annotated[AsyncSession, Depends(get_db)]) -> DailyReviewView:
    return await get_daily_review(db, review_date)


@router.put(
    "/daily-reviews/{review_date}", response_model=DailyReviewView, dependencies=[Depends(require_origin)]
)
async def daily_put(
    review_date: date,
    payload: DailyReviewInput,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DailyReviewView:
    return await save_daily_review(db, review_date, payload)


@router.get("/options", response_model=TradingOptionsView)
async def options_get(db: Annotated[AsyncSession, Depends(get_db)]) -> TradingOptionsView:
    return await get_options(db)


@router.patch("/options", response_model=TradingOptionsView, dependencies=[Depends(require_origin)])
async def options_patch(
    payload: TradingOptionsUpdate, db: Annotated[AsyncSession, Depends(get_db)]
) -> TradingOptionsView:
    return await update_options(db, payload)


@router.get("/export.xlsx")
async def export_xlsx(
    db: Annotated[AsyncSession, Depends(get_db)],
    from_date: Annotated[date | None, Query(alias="from")] = None,
    to_date: Annotated[date | None, Query(alias="to")] = None,
) -> Response:
    output = await create_export(db, from_date, to_date)
    suffix = "_".join(item.isoformat() for item in (from_date, to_date) if item) or date.today().isoformat()
    return Response(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''交易复盘_{suffix}.xlsx",
            "Cache-Control": "private, no-store",
        },
    )


ALLOWED_IMAGE_TYPES = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
}
MAX_ATTACHMENT_SIZE = 15 * 1024 * 1024


@router.post(
    "/trades/{trade_id}/attachments",
    response_model=TradeAttachmentView,
    dependencies=[Depends(require_origin)],
)
async def attachment_create(
    trade_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    file: Annotated[UploadFile, File()],
) -> TradeAttachmentView:
    row = await db.scalar(
        select(Trade).where(Trade.id == trade_id, Trade.deleted_at.is_(None)).with_for_update()
    )
    if row is None:
        raise ApiError(404, "交易记录不存在")
    count = int(
        await db.scalar(
            select(func.count()).select_from(TradeAttachment).where(TradeAttachment.trade_id == trade_id)
        )
        or 0
    )
    if count >= 10:
        raise ApiError(400, "每笔交易最多上传 10 张截图")
    data = await file.read(MAX_ATTACHMENT_SIZE + 1)
    if len(data) > MAX_ATTACHMENT_SIZE:
        raise ApiError(400, "截图不能超过 15 MB")
    try:
        image = Image.open(BytesIO(data))
        image.verify()
        image = Image.open(BytesIO(data))
        actual_width, actual_height = image.size
        image_format = image.format or ""
    except (UnidentifiedImageError, OSError) as error:
        raise ApiError(400, "截图内容不合法") from error
    if image_format not in ALLOWED_IMAGE_TYPES:
        raise ApiError(400, "只支持 JPEG、PNG 或 WebP 截图")
    content_type, extension = ALLOWED_IMAGE_TYPES[image_format]
    object_key = f"trades/{trade_id}/{uuid.uuid4()}.{extension}"
    client = get_minio()
    await run_in_threadpool(
        client.put_object,
        settings.minio_bucket,
        object_key,
        BytesIO(data),
        len(data),
        content_type=content_type,
    )
    attachment = TradeAttachment(
        trade_id=trade_id,
        object_key=object_key,
        file_name=(file.filename or f"attachment.{extension}")[:255],
        content_type=content_type,
        size=len(data),
        width=actual_width,
        height=actual_height,
        sort_order=count,
        is_cover=count == 0,
    )
    db.add(attachment)
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        await run_in_threadpool(client.remove_object, settings.minio_bucket, object_key)
        raise
    await db.refresh(attachment)
    return attachment_view(attachment)


@router.post("/trades/{trade_id}/attachments/complete", dependencies=[Depends(require_origin)])
async def attachment_complete_removed(trade_id: uuid.UUID) -> None:
    del trade_id
    raise ApiError(410, "附件上传协议已迁移，请使用 multipart 上传接口")


@router.patch(
    "/trades/{trade_id}/attachments/{attachment_id}",
    response_model=TradeAttachmentView,
    dependencies=[Depends(require_origin)],
)
async def attachment_update(
    trade_id: uuid.UUID,
    attachment_id: uuid.UUID,
    payload: AttachmentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TradeAttachmentView:
    if payload.is_cover:
        await db.execute(
            update(TradeAttachment).where(TradeAttachment.trade_id == trade_id).values(is_cover=False)
        )
    values = payload.model_dump(exclude_none=True)
    values["updated_at"] = datetime.now(UTC)
    result = await db.execute(
        update(TradeAttachment)
        .where(TradeAttachment.id == attachment_id, TradeAttachment.trade_id == trade_id)
        .values(**values)
        .returning(TradeAttachment)
    )
    row = result.scalar_one_or_none()
    if row is None:
        await db.rollback()
        raise ApiError(404, "未找到截图")
    await db.commit()
    return attachment_view(row)


@router.delete("/trades/{trade_id}/attachments/{attachment_id}", dependencies=[Depends(require_origin)])
async def attachment_delete(
    trade_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    row = await db.scalar(
        select(TradeAttachment).where(
            TradeAttachment.id == attachment_id, TradeAttachment.trade_id == trade_id
        )
    )
    if row is None:
        raise ApiError(404, "未找到截图")
    await db.execute(delete(TradeAttachment).where(TradeAttachment.id == attachment_id))
    await db.commit()
    try:
        await run_in_threadpool(get_minio().remove_object, settings.minio_bucket, row.object_key)
    except Exception as error:
        if not is_minio_error(error):
            raise
    return {"deleted": True}


@router.get("/files/{attachment_id}")
async def attachment_file(
    attachment_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    row = await db.scalar(select(TradeAttachment).where(TradeAttachment.id == attachment_id))
    if row is None:
        raise ApiError(404, "未找到截图")
    try:
        stream = await run_in_threadpool(get_minio().get_object, settings.minio_bucket, row.object_key)
    except Exception as error:
        if is_minio_error(error):
            raise ApiError(404, "未找到截图文件") from error
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
            "Content-Disposition": f"inline; filename*=UTF-8''{row.file_name}",
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
