import uuid

import pytest

from app.models import TradingRule
from app.routers.rules import create_rule, list_rules, to_view, update_rule
from app.schemas import TradingRuleInput


class _ScalarResult:
    def all(self) -> list[object]:
        return []


class _Db:
    statement = None
    scalar_statement = None

    async def scalars(self, statement: object) -> _ScalarResult:
        self.statement = statement
        return _ScalarResult()

    async def scalar(self, statement: object) -> int:
        self.scalar_statement = statement
        return 23


def test_trading_rule_model_exposes_comment_column_with_default() -> None:
    assert TradingRule.__table__.c.comment.nullable is False
    assert TradingRule.__table__.c.comment.server_default is not None


def test_trading_rule_model_exposes_rule_type_column_with_default() -> None:
    assert TradingRule.__table__.c.rule_type.nullable is False
    assert TradingRule.__table__.c.rule_type.server_default is not None


def test_rule_view_normalizes_legacy_null_text_fields() -> None:
    row = TradingRule(
        id=uuid.uuid4(),
        title="纪律",
        description="",
        sort_order=0,
        active=True,
        version=1,
    )
    row.rule_type = None  # type: ignore[assignment]
    row.comment = None  # type: ignore[assignment]

    view = to_view(row)

    assert view.rule_type == ""
    assert view.comment == ""


@pytest.mark.asyncio
async def test_list_rules_searches_title_description_and_comment() -> None:
    db = _Db()
    result = await list_rules(db, q="纪律", rule_type="趋势方向", page=2, page_size=20)

    sql = str(db.statement)
    assert "trading_rules.title" in sql
    assert "trading_rules.description" in sql
    assert "trading_rules.comment" in sql
    assert "trading_rules.rule_type" in sql
    assert "trading_rules.id" in sql
    assert result.total == 23
    assert result.page == 2
    assert result.page_size == 20
    assert result.total_pages == 2


def test_trading_rule_input_allows_blank_title_but_requires_rule_type() -> None:
    assert TradingRuleInput(title="  ", rule_type=" 趋势方向 ").title == ""
    with pytest.raises(ValueError):
        TradingRuleInput(title="规则", rule_type="  ")


class _RuleDb:
    def __init__(self, existing: TradingRule | None = None) -> None:
        self.existing = existing
        self.added: TradingRule | None = None

    def add(self, row: TradingRule) -> None:
        self.added = row

    async def scalar(self, _: object) -> TradingRule | None:
        return self.existing

    async def commit(self) -> None:
        return None

    async def refresh(self, _: TradingRule) -> None:
        return None


@pytest.mark.asyncio
async def test_create_and_update_rule_persist_rule_type_and_return_it() -> None:
    payload = TradingRuleInput(title="纪律", rule_type="entry")
    create_db = _RuleDb()

    created = await create_rule(payload, create_db)  # type: ignore[arg-type]

    assert create_db.added is not None
    assert create_db.added.rule_type == "entry"
    assert created.rule_type == "entry"

    existing = TradingRule(
        id=uuid.uuid4(), title="纪律", rule_type="entry", version=1
    )
    update_db = _RuleDb(existing)
    updated = await update_rule(
        existing.id,
        TradingRuleInput(title="纪律", rule_type="exit", version=1),
        update_db,  # type: ignore[arg-type]
    )

    assert existing.rule_type == "exit"
    assert updated.rule_type == "exit"
