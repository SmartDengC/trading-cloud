from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.calculations import calculate_executions, calculate_trade, decimal_string


@dataclass
class SampleTrade:
    status: str = "closed"
    side: str = "long"
    position_basis: str = "quantity"
    entry_at: datetime = datetime(2026, 7, 23, 1, 0, tzinfo=UTC)
    exit_at: datetime | None = datetime(2026, 7, 23, 1, 45, tzinfo=UTC)
    entry_price: Decimal = Decimal("100")
    exit_price: Decimal | None = Decimal("110")
    position_size: Decimal = Decimal("2")
    fees: Decimal = Decimal("1")
    fx_to_cny: Decimal = Decimal("7.2")
    planned_risk_amount: Decimal | None = Decimal("10")


@dataclass
class SampleExecution:
    action: str
    executed_at: datetime
    price: Decimal
    quantity: Decimal
    fee: Decimal = Decimal("0")


def test_quantity_long_calculation_matches_frontend_contract() -> None:
    result = calculate_trade(SampleTrade())
    assert decimal_string(result.gross_pnl) == "20"
    assert decimal_string(result.net_pnl) == "19"
    assert decimal_string(result.pnl_cny) == "136.8"
    assert decimal_string(result.r_multiple) == "1.9"
    assert result.hold_minutes == 45
    assert result.is_winning is True


def test_notional_short_calculation() -> None:
    trade = SampleTrade(
        side="short",
        position_basis="notional",
        exit_price=Decimal("90"),
        position_size=Decimal("1000"),
        fees=Decimal("0"),
        fx_to_cny=Decimal("1"),
    )
    result = calculate_trade(trade)
    assert decimal_string(result.net_pnl) == "100"
    assert result.is_winning is True


def test_open_trade_has_no_calculated_result() -> None:
    result = calculate_trade(SampleTrade(status="open", exit_at=None, exit_price=None))
    assert result.gross_pnl is None
    assert result.hold_minutes is None
    assert result.is_winning is None


def test_multiple_executions_use_weighted_prices_and_all_fees() -> None:
    executions = [
        SampleExecution("entry", datetime(2026, 7, 23, 1, 0, tzinfo=UTC), Decimal("100"), Decimal("1")),
        SampleExecution("entry", datetime(2026, 7, 23, 1, 10, tzinfo=UTC), Decimal("98"), Decimal("1")),
        SampleExecution("exit", datetime(2026, 7, 23, 1, 30, tzinfo=UTC), Decimal("105"), Decimal("1"), Decimal("1")),
        SampleExecution("exit", datetime(2026, 7, 23, 1, 45, tzinfo=UTC), Decimal("108"), Decimal("1"), Decimal("1")),
    ]
    result = calculate_executions(
        executions,
        side="long",
        position_basis="quantity",
        planned_risk_amount=Decimal("10"),
        fx_to_cny=Decimal("1"),
    )
    assert decimal_string(result.gross_pnl) == "15"
    assert decimal_string(result.net_pnl) == "13"
    assert result.hold_minutes == 45
