import logging
import re
import uuid

from fastapi.testclient import TestClient

from app.main import HealthcheckAccessLogFilter, app


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


def test_access_log_filter_suppresses_only_container_health_checks() -> None:
    access_filter = HealthcheckAccessLogFilter()
    message = '%s - "%s %s HTTP/%s" %s'

    ready = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        message,
        ("127.0.0.1:34394", "GET", "/health/ready", "1.1", 200),
        None,
    )
    live = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        message,
        ("127.0.0.1:34394", "GET", "/health/live?verbose=1", "1.1", 200),
        None,
    )
    api = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        0,
        message,
        ("172.18.0.3:51920", "GET", "/api/trading/trades", "1.1", 200),
        None,
    )

    assert access_filter.filter(ready) is False
    assert access_filter.filter(live) is False
    assert access_filter.filter(api) is True
