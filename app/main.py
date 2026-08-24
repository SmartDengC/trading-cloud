from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.errors import install_error_handlers
from app.routers import auth, reviews, trading
from app.storage import get_minio

settings = get_settings()
app = FastAPI(title="Trading Cloud", version="0.1.0")
install_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Accept", "X-Requested-With"],
)
app.include_router(auth.router)
app.include_router(reviews.router)
app.include_router(trading.router)


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
