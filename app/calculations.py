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


class ExecutionLike(Protocol):
    action: str
    executed_at: datetime
    price: Decimal
    quantity: Decimal
    fee: Decimal


def calculate_executions(
    executions: list[ExecutionLike],
    *,
    side: str,
    position_basis: str,
    planned_risk_amount: Decimal | None,
    fx_to_cny: Decimal,
) -> TradeCalculation:
    entries = [item for item in executions if item.action == "entry"]
    exits = [item for item in executions if item.action == "exit"]
    if not entries or not exits:
        return TradeCalculation(None, None, None, None, None, None)

    entry_quantity = sum((item.quantity for item in entries), Decimal(0))
    exit_quantity = sum((item.quantity for item in exits), Decimal(0))
    if entry_quantity <= 0 or exit_quantity <= 0:
        raise ValueError("执行明细数量不合法")
    entry_notional = sum((item.price * item.quantity for item in entries), Decimal(0))
    exit_notional = sum((item.price * item.quantity for item in exits), Decimal(0))
    average_entry = entry_notional / entry_quantity
    average_exit = exit_notional / exit_quantity
    direction = Decimal(1) if side == "long" else Decimal(-1)
    delta = (average_exit - average_entry) * direction
    matched = min(entry_quantity, exit_quantity)
    gross = (
        delta * matched
        if position_basis == "quantity"
        else delta / average_entry * matched
    )
    fees = sum((item.fee for item in executions), Decimal(0))
    net = gross - fees
    pnl_cny = net * fx_to_cny
    r_multiple = net / planned_risk_amount if planned_risk_amount and planned_risk_amount > 0 else None
    entry_time = min(item.executed_at for item in entries)
    exit_time = max(item.executed_at for item in exits)
    elapsed_minutes = Decimal(str((exit_time - entry_time).total_seconds())) / Decimal(60)
    hold_minutes = max(0, int(elapsed_minutes.quantize(Decimal("1"), rounding=ROUND_HALF_UP)))
    return TradeCalculation(clean(gross), clean(net), clean(pnl_cny), clean(r_multiple), hold_minutes, net > 0)


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
