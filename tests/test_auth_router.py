from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Response

from app.config import Settings
from app.routers import auth as auth_router
from app.schemas import EncryptedPasswordInput, LoginInput


@pytest.mark.asyncio
async def test_login_sets_a_two_hour_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    password_hash = Mock()
    password_hash.verify.return_value = True
    create_session = AsyncMock(return_value=(None, "session-token"))
    monkeypatch.setattr(auth_router, "get_password_hash", lambda: password_hash)
    monkeypatch.setattr(auth_router, "create_session", create_session)
    monkeypatch.setattr(auth_router, "get_login_encryption_key", lambda _: object())
    monkeypatch.setattr(auth_router, "decrypt_password", lambda *_args, **_kwargs: "secret")

    response = Response()
    settings = Settings(admin_password_hash="configured", session_hours=2)

    await auth_router.login(
        LoginInput(
            username="admin",
            encrypted_password=EncryptedPasswordInput(
                algorithm="RSA-OAEP-256+A256GCM",
                key_id="a" * 64,
                encrypted_key="encrypted-key",
                iv="iv",
                ciphertext="ciphertext",
            ),
        ),
        response,
        AsyncMock(),
        settings,
    )

    assert "Max-Age=7200" in response.headers["set-cookie"]
    create_session.assert_awaited_once()
