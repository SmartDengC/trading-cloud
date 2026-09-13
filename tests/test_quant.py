from __future__ import annotations

from pathlib import Path

import pytest

from app.models import QuantBacktest, QuantStrategy
from app.quant_seed_data import INITIAL_QUANT_STRATEGIES
from app.routers.quant import router as quant_router
from app.schemas import QuantBacktestInput, QuantStrategyInput


def test_quant_models_define_shared_strategy_and_cascade_relationship() -> None:
    assert QuantStrategy.__tablename__ == "quant_strategies"
    assert QuantBacktest.__tablename__ == "quant_backtests"
    foreign_key = next(iter(QuantBacktest.strategy_id.property.columns[0].foreign_keys))
    assert foreign_key.target_fullname == "quant_strategies.id"
    assert foreign_key.ondelete == "CASCADE"


def test_quant_input_normalizes_optional_percent_metrics() -> None:
    payload = QuantBacktestInput(
        run_at="2026-09-13T08:00:00Z",
        timerange="20250101-20260101",
        pairs="BTC/USDT, ETH/USDT",
        timeframe="5m",
        trade_count=12,
        total_return="12.50",
        win_rate="",
        max_drawdown=None,
        profit_factor="1.25",
        notes="manual import",
    )
    assert payload.total_return == "12.50"
    assert payload.win_rate is None
    assert payload.max_drawdown is None
    assert payload.profit_factor == "1.25"

    for value in ("0", "-12.5"):
        assert QuantBacktestInput(
            run_at="2026-09-13T08:00:00Z",
            timerange="20250101-20260101",
            pairs="BTC/USDT",
            timeframe="5m",
            total_return=value,
        ).total_return == value


def test_quant_input_rejects_non_numeric_metrics() -> None:
    with pytest.raises(ValueError, match="总收益率不合法"):
        QuantBacktestInput(
            run_at="2026-09-13T08:00:00Z",
            timerange="20250101-20260101",
            pairs="BTC/USDT",
            timeframe="5m",
            total_return="12%",
        )


def test_quant_seed_contains_three_versioned_snapshots() -> None:
    assert {item.file_name for item in INITIAL_QUANT_STRATEGIES} == {
        "FirstStrategy.py",
        "Strategy001.py",
        "sample_strategy.py",
    }
    assert any(item.is_example and item.name == "SampleStrategy" for item in INITIAL_QUANT_STRATEGIES)
    for item in INITIAL_QUANT_STRATEGIES:
        source = Path(item.source_path).read_text(encoding="utf-8")
        assert source.strip()
        assert item.name in source
        assert all(section in item.explanation for section in ("指标", "入场", "出场", "风控", "注意事项"))


def test_quant_routes_are_registered_under_api_prefix() -> None:
    paths = {route.path for route in quant_router.routes}
    assert "/api/quant/strategies" in paths
    assert "/api/quant/strategies/{strategy_id}" in paths
    assert "/api/quant/strategies/{strategy_id}/backtests" in paths
    assert "/api/quant/backtests/{backtest_id}" in paths


def test_quant_strategy_input_requires_the_snapshot_fields() -> None:
    payload = QuantStrategyInput(
        name="DemoStrategy",
        file_name="DemoStrategy.py",
        source_code="class DemoStrategy: pass",
        timeframe="5m",
        is_example=False,
        summary="demo",
        explanation="# 指标\n\n## 入场\n\n## 出场\n\n## 风控\n\n## 注意事项",
    )
    assert payload.file_name == "DemoStrategy.py"
