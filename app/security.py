from __future__ import annotations

import hashlib
import secrets
import sys
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, Request
from pwdlib import PasswordHash
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.errors import ApiError
from app.models import AuthSession

SESSION_TOUCH_INTERVAL = timedelta(minutes=5)


@lru_cache
def get_password_hash() -> PasswordHash:
    return PasswordHash.recommended()


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


async def current_session(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    cookie: Annotated[str | None, Cookie(alias="trading_session")] = None,
) -> AuthSession:
    token = request.cookies.get(settings.session_cookie) or cookie
    if not token:
        raise ApiError(401, "请先登录")
    now = datetime.now(UTC)
    session = await db.scalar(
        select(AuthSession).where(
            AuthSession.token_hash == hash_session_token(token), AuthSession.expires_at > now
        )
    )
    if session is None:
        raise ApiError(401, "登录已失效，请重新登录")
    cutoff = now - SESSION_TOUCH_INTERVAL
    if session.last_seen_at <= cutoff:
        touched_id = await db.scalar(
            update(AuthSession)
            .where(AuthSession.id == session.id, AuthSession.last_seen_at <= cutoff)
            .values(last_seen_at=now)
            .returning(AuthSession.id)
        )
        if touched_id is not None:
            session.last_seen_at = now
            await db.commit()
    return session


def require_origin(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> None:
    origin = request.headers.get("origin")
    if origin != settings.frontend_origin:
        raise ApiError(403, "请求来源不合法")


async def create_session(db: AsyncSession, username: str, days: int) -> tuple[AuthSession, str]:
    now = datetime.now(UTC)
    await db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))
    token = new_session_token()
    session = AuthSession(
        token_hash=hash_session_token(token),
        username=username,
        expires_at=now + timedelta(days=days),
        last_seen_at=now,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, token


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.security 'password'")
    print(get_password_hash().hash(sys.argv[1]))


if __name__ == "__main__":
    main()
