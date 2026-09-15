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
from app.login_crypto import (
    LoginEncryptionError,
    LoginEncryptionKeyMismatch,
    LoginEncryptionNotConfigured,
    decrypt_password,
    get_login_encryption_key,
)
from app.models import AuthSession
from app.schemas import LoginEncryptionKeyView, LoginInput, SessionView, UserView
from app.security import create_session, current_session, get_password_hash, require_origin

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/encryption-key", response_model=LoginEncryptionKeyView)
async def encryption_key(
    response: Response,
    settings: Annotated[Settings, Depends(get_settings)],
) -> LoginEncryptionKeyView:
    try:
        key = get_login_encryption_key(settings)
    except LoginEncryptionNotConfigured as error:
        raise ApiError(503, str(error)) from error
    response.headers["Cache-Control"] = "private, no-store"
    return LoginEncryptionKeyView(
        algorithm="RSA-OAEP-256+A256GCM",
        key_id=key.key_id,
        public_key=key.public_key,
    )


@router.post("/login", response_model=SessionView, dependencies=[Depends(require_origin)])
async def login(
    payload: LoginInput,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SessionView:
    started = monotonic()
    try:
        encryption_key = get_login_encryption_key(settings)
    except LoginEncryptionNotConfigured as error:
        raise ApiError(503, str(error)) from error

    password = ""
    try:
        password = decrypt_password(
            encryption_key,
            algorithm=payload.encrypted_password.algorithm,
            key_id=payload.encrypted_password.key_id,
            encrypted_aes_key=payload.encrypted_password.encrypted_key,
            iv=payload.encrypted_password.iv,
            ciphertext=payload.encrypted_password.ciphertext,
            username=payload.username,
        )
    except LoginEncryptionKeyMismatch as error:
        raise ApiError(409, str(error)) from error
    except LoginEncryptionError:
        password = ""

    valid = bool(settings.admin_password_hash) and payload.username == settings.admin_username
    if valid and password:
        try:
            valid = get_password_hash().verify(password, settings.admin_password_hash)
        except Exception:
            valid = False
    remaining = 0.35 - (monotonic() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)
    if not settings.admin_password_hash:
        raise ApiError(503, "管理员密码尚未配置")
    if not valid:
        raise ApiError(401, "账号或密码错误")
    _, token = await create_session(db, payload.username, settings.session_hours)
    response.set_cookie(
        settings.session_cookie,
        token,
        max_age=settings.session_hours * 60 * 60,
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
