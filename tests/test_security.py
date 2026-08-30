import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from fastapi import Request

from app.config import Settings
from app.errors import ApiError
from app.models import AuthSession
from app.security import current_session, hash_session_token, new_session_token, require_origin


def request_with_session_cookie(token: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"cookie", f"trading_session={token}".encode())],
        }
    )


def request_with_origin(origin: str) -> Request:
    return Request(
        {
            "type": "http",
            "headers": [(b"origin", origin.encode())],
        }
    )


def auth_session(*, last_seen_at: datetime) -> AuthSession:
    return AuthSession(
        id=uuid.uuid4(),
        token_hash=hash_session_token("token"),
        username="admin",
        expires_at=datetime.now(UTC) + timedelta(days=1),
        last_seen_at=last_seen_at,
    )


def test_session_tokens_are_random_and_only_hash_is_persisted() -> None:
    first = new_session_token()
    second = new_session_token()
    assert first != second
    assert len(hash_session_token(first)) == 64
    assert first not in hash_session_token(first)


def test_empty_session_cookie_domain_is_disabled() -> None:
    assert Settings(session_cookie_domain="").session_cookie_domain is None
    assert Settings(session_cookie_domain="example.com").session_cookie_domain == "example.com"


def test_frontend_origins_parse_a_trimmed_deduplicated_allowlist() -> None:
    settings = Settings(
        frontend_origins=" https://app.example.com/ , http://localhost:3000, https://app.example.com "
    )

    assert settings.frontend_origin_list == [
        "https://app.example.com",
        "http://localhost:3000",
    ]


def test_require_origin_accepts_any_configured_frontend_origin() -> None:
    settings = Settings(frontend_origins="https://app.example.com,http://localhost:3000")

    require_origin(request_with_origin("http://localhost:3000"), settings)


def test_require_origin_rejects_an_unconfigured_origin() -> None:
    settings = Settings(frontend_origins="https://app.example.com,http://localhost:3000")

    with pytest.raises(ApiError, match="请求来源不合法"):
        require_origin(request_with_origin("https://not-allowed.example"), settings)


async def test_recent_session_does_not_write_last_seen_at() -> None:
    session = auth_session(last_seen_at=datetime.now(UTC) - timedelta(minutes=1))
    db = AsyncMock()
    db.scalar.return_value = session

    result = await current_session(request_with_session_cookie("token"), db, Settings())

    assert result is session
    db.commit.assert_not_awaited()
    db.scalar.assert_awaited_once()


async def test_stale_session_updates_last_seen_at_once() -> None:
    previous_seen_at = datetime.now(UTC) - timedelta(minutes=10)
    session = auth_session(last_seen_at=previous_seen_at)
    db = AsyncMock()
    db.scalar.side_effect = [session, session.id]

    result = await current_session(request_with_session_cookie("token"), db, Settings())

    assert result is session
    assert session.last_seen_at > previous_seen_at
    db.commit.assert_awaited_once()
    assert db.scalar.await_count == 2


async def test_stale_session_does_not_commit_when_another_request_touched_it() -> None:
    session = auth_session(last_seen_at=datetime.now(UTC) - timedelta(minutes=10))
    db = AsyncMock()
    db.scalar.side_effect = [session, None]

    await current_session(request_with_session_cookie("token"), db, Settings())

    db.commit.assert_not_awaited()


async def test_invalid_or_expired_session_is_rejected() -> None:
    db = AsyncMock()
    db.scalar.return_value = None

    with pytest.raises(ApiError, match="登录已失效"):
        await current_session(request_with_session_cookie("expired-token"), db, Settings())

    db.commit.assert_not_awaited()
