import pytest

from app.models import TradingRule
from app.routers.rules import list_rules


class _ScalarResult:
    def all(self) -> list[object]:
        return []


class _Db:
    statement = None

    async def scalars(self, statement: object) -> _ScalarResult:
        self.statement = statement
        return _ScalarResult()


def test_trading_rule_model_exposes_comment_column_with_default() -> None:
    assert TradingRule.__table__.c.comment.nullable is False
    assert TradingRule.__table__.c.comment.server_default is not None


@pytest.mark.asyncio
async def test_list_rules_searches_title_description_and_comment() -> None:
    db = _Db()
    await list_rules(db, q="纪律")

    sql = str(db.statement)
    assert "trading_rules.title" in sql
    assert "trading_rules.description" in sql
    assert "trading_rules.comment" in sql
