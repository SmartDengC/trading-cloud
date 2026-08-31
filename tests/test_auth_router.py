from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Response

from app.config import Settings
from app.routers import auth as auth_router
from app.schemas import LoginInput


@pytest.mark.asyncio
async def test_login_sets_a_two_hour_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    password_hash = Mock()
    password_hash.verify.return_value = True
    create_session = AsyncMock(return_value=(None, "session-token"))
    monkeypatch.setattr(auth_router, "get_password_hash", lambda: password_hash)
    monkeypatch.setattr(auth_router, "create_session", create_session)

    response = Response()
    settings = Settings(admin_password_hash="configured", session_hours=2)

    await auth_router.login(
        LoginInput(username="admin", password="secret"),
        response,
        AsyncMock(),
        settings,
    )

    assert "Max-Age=7200" in response.headers["set-cookie"]
    create_session.assert_awaited_once()
