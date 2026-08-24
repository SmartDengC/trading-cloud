from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, localcontext
from typing import Protocol


class CalculableTrade(Protocol):
    status: str
    side: str
    position_basis: str
    entry_at: datetime
    exit_at: datetime | None
    entry_price: Decimal
    exit_price: Decimal | None
    position_size: Decimal
    fees: Decimal
    fx_to_cny: Decimal
    planned_risk_amount: Decimal | None


@dataclass(frozen=True)
class TradeCalculation:
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    pnl_cny: Decimal | None
    r_multiple: Decimal | None
    hold_minutes: int | None
    is_winning: bool | None


def clean(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP).normalize()


def calculate_trade(trade: CalculableTrade) -> TradeCalculation:
    if trade.status != "closed" or trade.exit_at is None or trade.exit_price is None:
        return TradeCalculation(None, None, None, None, None, None)
    if trade.entry_price == 0:
        raise ValueError("交易计算字段不完整")

    with localcontext() as context:
        context.prec = 40
        context.rounding = ROUND_HALF_UP
        direction = Decimal(1) if trade.side == "long" else Decimal(-1)
        delta = (trade.exit_price - trade.entry_price) * direction
        gross = (
            delta * trade.position_size
            if trade.position_basis == "quantity"
            else delta / trade.entry_price * trade.position_size
        )
        net = gross - trade.fees
        pnl_cny = net * trade.fx_to_cny
        risk = trade.planned_risk_amount
        r_multiple = net / risk if risk is not None and risk > 0 else None
        elapsed_minutes = Decimal(str((trade.exit_at - trade.entry_at).total_seconds())) / Decimal(60)
        hold_minutes = max(0, int(elapsed_minutes.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
        return TradeCalculation(
            clean(gross), clean(net), clean(pnl_cny), clean(r_multiple), hold_minutes, net > 0
        )


def decimal_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"
