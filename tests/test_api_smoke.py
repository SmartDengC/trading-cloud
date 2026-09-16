from __future__ import annotations

import base64
import os
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

API_URL = os.getenv("TEST_API_URL")
ORIGIN = os.getenv("TEST_FRONTEND_ORIGIN", "http://localhost:3000")
USERNAME = os.getenv("TEST_ADMIN_USERNAME")
PASSWORD = os.getenv("TEST_ADMIN_PASSWORD")


def encode_base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def encrypted_login_payload(client: httpx.Client) -> dict[str, object]:
    encryption_key = client.get("/api/auth/encryption-key").json()
    username = USERNAME or ""
    public_der = base64.urlsafe_b64decode(
        encryption_key["publicKey"] + "=" * (-len(encryption_key["publicKey"]) % 4)
    )
    public_key = serialization.load_der_public_key(public_der)
    assert isinstance(public_key, rsa.RSAPublicKey)
    ciphertext = public_key.encrypt(
        (PASSWORD or "").encode(),
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "username": username,
        "keyId": encryption_key["keyId"],
        "encryptedPassword": encode_base64url(ciphertext),
    }


@pytest.mark.skipif(
    not API_URL or not USERNAME or not PASSWORD,
    reason="requires a disposable running API and TEST_API_URL/TEST_ADMIN_*",
)
def test_authenticated_business_api_lifecycle() -> None:
    headers = {"Origin": ORIGIN}
    review_slug = "2099-12-31"
    with httpx.Client(base_url=API_URL or "", timeout=30, follow_redirects=True) as client:
        rejected = client.post(
            "/api/auth/login",
            headers={"Origin": "https://not-allowed.example"},
            json=encrypted_login_payload(client),
        )
        assert rejected.status_code == 403
        assert rejected.json()["statusCode"] == 403

        login = client.post(
            "/api/auth/login",
            headers=headers,
            json=encrypted_login_payload(client),
        )
        assert login.status_code == 200
        assert client.get("/api/auth/session").json()["loggedIn"] is True

        review = client.get(f"/api/reviews/daily/{review_slug}")
        review_version = review.json()["version"] if review.status_code == 200 else None
        review_payload: dict[str, object] = {
            "title": "Trading Cloud smoke test",
            "dateLabel": review_slug,
            "content": "# Smoke test",
        }
        if review_version is not None:
            review_payload["version"] = review_version
        saved_review = client.put(f"/api/reviews/daily/{review_slug}", headers=headers, json=review_payload)
        assert saved_review.status_code == 200

        trade_payload: dict[str, object] = {
            "status": "closed",
            "tradeDate": review_slug,
            "instrumentCode": "BTCUSDT",
            "symbol": "BTC/USDT smoke",
            "market": "crypto",
            "side": "long",
            "strategy": "趋势突破",
            "timeframe": "5分",
            "entryAt": "2099-12-31T01:00:00Z",
            "exitAt": "2099-12-31T01:45:00Z",
            "entryReason": "smoke",
            "exitReason": "smoke",
            "entryPrice": "100",
            "exitPrice": "110",
            "positionSize": "2",
            "positionBasis": "quantity",
            "settlementCurrency": "USDT",
            "plannedRiskAmount": "10",
            "fees": "1",
            "fxToCny": "7.2",
            "executionGrade": "A",
            "errorTags": ["自动化测试"],
        }
        created = client.post("/api/trading/trades", headers=headers, json=trade_payload)
        assert created.status_code == 200
        trade = created.json()
        trade_id = trade["id"]
        assert trade["netPnl"] == "19"

        conflict_payload = {**trade_payload, "version": trade["version"] + 1}
        conflict = client.patch(f"/api/trading/trades/{trade_id}", headers=headers, json=conflict_payload)
        assert conflict.status_code == 409

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
            b"\x00\x00\x00\rIDAT\x08\xd7c\xf8\xcf\xc0\xf0\x1f\x00\x05"
            b"\x00\x01\xff\x89\x99=\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        uploaded = client.post(
            f"/api/trading/trades/{trade_id}/attachments",
            headers=headers,
            files={"file": ("smoke.png", png, "image/png")},
        )
        assert uploaded.status_code == 200
        attachment_id = uploaded.json()["id"]
        file_response = client.get(f"/api/trading/files/{attachment_id}")
        assert file_response.status_code == 200
        assert file_response.content == png

        daily = client.get(f"/api/trading/daily-reviews/{review_slug}")
        assert daily.status_code == 200
        daily_payload: dict[str, object] = {
            "reviewDate": review_slug,
            "dailySummary": "smoke",
        }
        if daily.json()["version"] > 0:
            daily_payload["version"] = daily.json()["version"]
        saved_daily = client.put(
            f"/api/trading/daily-reviews/{review_slug}", headers=headers, json=daily_payload
        )
        assert saved_daily.status_code == 200

        assert client.get("/api/trading/dashboard").status_code == 200
        options = client.get("/api/trading/options")
        assert options.status_code == 200
        option_label = "smoke-option-delete"
        created_option = client.patch(
            "/api/trading/options",
            headers=headers,
            json={
                "options": [
                    {
                        "kind": "strategy",
                        "label": option_label,
                        "active": True,
                        "sortOrder": 999,
                    }
                ]
            },
        )
        assert created_option.status_code == 200
        option_id = next(
            item["id"] for item in created_option.json()["options"] if item["label"] == option_label
        )
        deleted_option = client.delete(f"/api/trading/options/{option_id}", headers=headers)
        assert deleted_option.status_code == 200
        assert all(item["id"] != option_id for item in deleted_option.json()["options"])
        assert (
            client.patch(
                "/api/trading/options",
                headers=headers,
                json={
                    "options": [],
                    "defaultUsdtCnyRate": options.json()["settings"]["defaultUsdtCnyRate"],
                },
            ).status_code
            == 200
        )
        export = client.get("/api/trading/export.xlsx")
        assert export.status_code == 200
        assert export.content.startswith(b"PK")

        deleted_attachment = client.delete(
            f"/api/trading/trades/{trade_id}/attachments/{attachment_id}", headers=headers
        )
        assert deleted_attachment.status_code == 200

        deleted_trade = client.delete(
            f"/api/trading/trades/{trade_id}",
            headers=headers,
            params={"version": trade["version"]},
        )
        assert deleted_trade.status_code == 200
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
        assert client.get("/api/auth/session").status_code == 401


@pytest.mark.skipif(
    not API_URL or not USERNAME or not PASSWORD,
    reason="requires a disposable running API and TEST_API_URL/TEST_ADMIN_*",
)
def test_authenticated_quant_strategy_lifecycle() -> None:
    headers = {"Origin": ORIGIN}
    strategy_name = f"SmokeQuant{uuid.uuid4().hex[:8]}"
    strategy_payload = {
        "name": strategy_name,
        "fileName": f"{strategy_name}.py",
        "sourceCode": f"class {strategy_name}: pass",
        "timeframe": "5m",
        "isExample": False,
        "summary": "smoke",
        "explanation": "# 指标\n\n## 入场\n\n## 出场\n\n## 风控\n\n## 注意事项",
    }
    with httpx.Client(base_url=API_URL or "", timeout=30, follow_redirects=True) as client:
        login = client.post(
            "/api/auth/login",
            headers=headers,
            json=encrypted_login_payload(client),
        )
        assert login.status_code == 200
        created = client.post("/api/quant/strategies", headers=headers, json=strategy_payload)
        assert created.status_code == 200
        strategy = created.json()
        strategy_id = strategy["id"]
        assert strategy["sourceCode"] == strategy_payload["sourceCode"]
        assert client.get("/api/quant/strategies").status_code == 200

        backtest = client.post(
            f"/api/quant/strategies/{strategy_id}/backtests",
            headers=headers,
            json={
                "runAt": "2099-12-31T01:00:00Z",
                "timerange": "20990101-20991231",
                "pairs": "BTC/USDT",
                "timeframe": "5m",
                "totalReturn": "12.5",
                "winRate": "55",
            },
        )
        assert backtest.status_code == 200
        assert backtest.json()["totalReturn"] == "12.50000000"
        detail = client.get(f"/api/quant/strategies/{strategy_id}")
        assert detail.status_code == 200
        assert len(detail.json()["backtests"]) == 1

        conflict = client.put(
            f"/api/quant/strategies/{strategy_id}",
            headers=headers,
            json={**strategy_payload, "version": strategy["version"] + 1},
        )
        assert conflict.status_code == 409
        assert client.delete(f"/api/quant/strategies/{strategy_id}", headers=headers).status_code == 200
        assert client.get(f"/api/quant/strategies/{strategy_id}").status_code == 404
        assert client.post("/api/auth/logout", headers=headers).status_code == 200
