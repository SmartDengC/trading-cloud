from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas import TradeExecutionInput, TradeInput, TradingOptionUpdate, validate_review_slug


def trade_payload() -> dict[str, object]:
    return {
        "status": "closed",
        "tradeDate": "2026-07-23",
        "symbol": "BTCUSDT",
        "market": "crypto",
        "side": "long",
        "strategy": "趋势突破",
        "timeframe": "5分",
        "entryAt": datetime(2026, 7, 23, 1, 0, tzinfo=UTC).isoformat(),
        "exitAt": datetime(2026, 7, 23, 2, 0, tzinfo=UTC).isoformat(),
        "entryReason": "突破",
        "exitReason": "止盈",
        "entryPrice": "100",
        "exitPrice": "110",
        "positionSize": "2",
        "positionBasis": "quantity",
        "settlementCurrency": "USDT",
        "plannedRiskAmount": "10",
        "fees": "0",
        "fxToCny": "7.2",
        "errorTags": ["计划外交易", "计划外交易"],
    }


def test_trade_input_accepts_camel_case_and_deduplicates_tags() -> None:
    value = TradeInput.model_validate(trade_payload())
    assert value.error_tags == ["计划外交易"]
    assert value.entry_price == "100"


def test_cny_forces_exchange_rate_to_one() -> None:
    payload = trade_payload()
    payload["settlementCurrency"] = "CNY"
    payload["fxToCny"] = "999"
    assert TradeInput.model_validate(payload).fx_to_cny == "1"


def test_closed_trade_requires_exit_fields() -> None:
    payload = trade_payload()
    payload["exitReason"] = None
    with pytest.raises(ValidationError, match="已平仓交易"):
        TradeInput.model_validate(payload)


def test_trade_time_requires_timezone_and_decimal_rejects_exponent() -> None:
    payload = trade_payload()
    payload["entryAt"] = "2026-07-23T01:00:00"
    with pytest.raises(ValidationError, match="必须包含时区"):
        TradeInput.model_validate(payload)

    payload = trade_payload()
    payload["entryPrice"] = "1e2"
    with pytest.raises(ValidationError, match="开仓价不合法"):
        TradeInput.model_validate(payload)


def test_review_slug_rules() -> None:
    validate_review_slug("daily", "2026-08-23")
    validate_review_slug("weekly", "2026-W34")
    with pytest.raises(ValueError, match="复盘类型或编号不合法"):
        validate_review_slug("weekly", "2026-08-23")


def test_trading_option_update_accepts_edit_payload() -> None:
    """验证 TradingOptionUpdate 能正确解析前端传入的 camelCase 编辑数据"""
    value = TradingOptionUpdate.model_validate(
        {
            "active": False,
            "kind": "symbol",
            "label": "沪深300",
            "sortOrder": 50,
        }
    )

    assert value.active is False
    assert value.kind == "symbol"
    assert value.label == "沪深300"
    assert value.sort_order == 50


def test_trade_execution_input_normalizes_decimal_and_timezone() -> None:
    value = TradeExecutionInput.model_validate(
        {
            "action": "entry",
            "executedAt": "2026-07-23T09:00:00+08:00",
            "price": "100.50",
            "quantity": "2",
            "fee": "0.1",
            "reason": "突破确认",
        }
    )
    assert value.price == "100.50"
    assert value.quantity == "2"
    assert value.executed_at.hour == 1
