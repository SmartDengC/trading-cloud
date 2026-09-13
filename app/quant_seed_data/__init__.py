from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QuantStrategySeed:
    name: str
    file_name: str
    timeframe: str
    is_example: bool
    summary: str
    explanation_file: str

    @property
    def source_path(self) -> Path:
        return Path(__file__).parent / self.file_name

    @property
    def explanation(self) -> str:
        return (Path(__file__).parent / self.explanation_file).read_text(encoding="utf-8")


INITIAL_QUANT_STRATEGIES = (
    QuantStrategySeed(
        name="FirstStrategy",
        file_name="FirstStrategy.py",
        timeframe="5m",
        is_example=False,
        summary="EMA20/EMA50 趋势交叉结合 RSI 和成交量过滤的做多策略。",
        explanation_file="FirstStrategy.md",
    ),
    QuantStrategySeed(
        name="Strategy001",
        file_name="Strategy001.py",
        timeframe="5m",
        is_example=False,
        summary="EMA20/EMA50/EMA100 与 Heikin Ashi 联合确认的趋势策略。",
        explanation_file="Strategy001.md",
    ),
    QuantStrategySeed(
        name="SampleStrategy",
        file_name="sample_strategy.py",
        timeframe="5m",
        is_example=True,
        summary="Freqtrade 官方风格的 RSI、TEMA、布林带示例策略，仅用于学习和改造。",
        explanation_file="SampleStrategy.md",
    ),
)
