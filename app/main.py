from __future__ import annotations

import logging
import re
import uuid
from time import perf_counter
from typing import Annotated

from fastapi import Depends, FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import RequestResponseEndpoint

from app.config import get_settings
from app.database import get_db
from app.errors import install_error_handlers
from app.routers import auth, market, memos, reviews, rules, trading
from app.storage import get_minio

settings = get_settings()
request_logger = logging.getLogger("trading.request")
request_id_pattern = re.compile(r"^[A-Za-z0-9._:-]{1,100}$")
app = FastAPI(title="Trading Cloud", version="0.1.0")
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.frontend_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Requested-With"],
)
app.include_router(auth.router)
app.include_router(market.router)
app.include_router(memos.router)
app.include_router(reviews.router)
app.include_router(rules.router)
app.include_router(trading.router)


@app.middleware("http")
async def record_request_timing(request: Request, call_next: RequestResponseEndpoint) -> Response:
    supplied_request_id = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied_request_id
        if request_id_pattern.fullmatch(supplied_request_id)
        else str(uuid.uuid4())
    )
    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (perf_counter() - started) * 1000
        request_logger.exception(
            "request_failed method=%s path=%s status=500 request_id=%s duration_ms=%.2f",
            request.method,
            request.url.path,
            request_id,
            duration_ms,
        )
        raise

    duration_ms = (perf_counter() - started) * 1000
    timing = f"app;dur={duration_ms:.2f}"
    existing_timing = response.headers.get("Server-Timing")
    response.headers["Server-Timing"] = (
        f"{existing_timing}, {timing}" if existing_timing else timing
    )
    response.headers["X-Request-ID"] = request_id
    request_logger.info(
        "request method=%s path=%s status=%s request_id=%s duration_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        request_id,
        duration_ms,
    )
    return response


@app.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready")
async def ready(db: Annotated[AsyncSession, Depends(get_db)]) -> dict[str, str]:
    await db.execute(text("SELECT 1"))
    client = get_minio()
    exists = await run_in_threadpool(client.bucket_exists, settings.minio_bucket)
    if not exists:
        from app.errors import ApiError

        raise ApiError(503, "附件存储尚未就绪")
    return {"status": "ready"}
