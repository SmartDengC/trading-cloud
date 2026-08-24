from __future__ import annotations

import asyncio
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db
from app.errors import ApiError
from app.models import AuthSession
from app.schemas import LoginInput, SessionView, UserView
from app.security import create_session, current_session, get_password_hash, require_origin

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=SessionView, dependencies=[Depends(require_origin)])
async def login(
    payload: LoginInput,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionView:
    started = monotonic()
    valid = bool(settings.admin_password_hash) and payload.username == settings.admin_username
    if valid:
        try:
            valid = get_password_hash().verify(payload.password, settings.admin_password_hash)
        except Exception:
            valid = False
    remaining = 0.35 - (monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)
    if not settings.admin_password_hash:
        raise ApiError(503, "管理员密码尚未配置")
    if not valid:
        raise ApiError(401, "账号或密码错误")
    _, token = await create_session(db, payload.username, settings.session_days)
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.session_secure,
        samesite="lax",
        path="/",
        domain=settings.session_cookie_domain,
    )
    return SessionView(logged_in=True, user=UserView(username=payload.username))


@router.get("/session", response_model=SessionView)
async def session_view(session: Annotated[AuthSession, Depends(current_session)]) -> SessionView:
    return SessionView(logged_in=True, user=UserView(username=session.username))


@router.post("/logout", dependencies=[Depends(require_origin)])
async def logout(
    response: Response,
    session: Annotated[AuthSession, Depends(current_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> dict[str, bool]:
    await db.execute(delete(AuthSession).where(AuthSession.id == session.id))
    await db.commit()
    response.delete_cookie(
        settings.session_cookie,
        path="/",
        secure=settings.session_secure,
        httponly=True,
        samesite="lax",
        domain=settings.session_cookie_domain,
    )
    return {"loggedIn": False}
