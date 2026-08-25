import logging
import re
import uuid

from fastapi.testclient import TestClient

from app.main import app


def test_liveness_does_not_require_external_dependencies() -> None:
    response = TestClient(app).get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_request_timing_preserves_a_valid_request_id() -> None:
    response = TestClient(app).get("/health/live", headers={"X-Request-ID": "browser-request-1"})

    assert response.headers["X-Request-ID"] == "browser-request-1"
    assert re.fullmatch(r"app;dur=\d+\.\d{2}", response.headers["Server-Timing"])


def test_request_timing_replaces_an_invalid_request_id() -> None:
    response = TestClient(app).get("/health/live", headers={"X-Request-ID": "invalid id"})

    assert uuid.UUID(response.headers["X-Request-ID"])


def test_request_log_does_not_include_query_or_cookie(caplog) -> None:
    with caplog.at_level(logging.INFO, logger="trading.request"):
        response = TestClient(app).get(
            "/health/live?token=do-not-log",
            headers={"Cookie": "trading_session=do-not-log"},
        )

    assert response.status_code == 200
    assert "do-not-log" not in caplog.text
