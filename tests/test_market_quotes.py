from datetime import timedelta

import httpx
import pytest

from app.market_quotes import SinaQuoteClient, SinaQuoteError, parse_sina_quotes


def test_parse_sina_quotes_normalizes_mainland_quote() -> None:
    raw = 'var hq_str_sh000001="上证指数,3990.00,3952.18,3986.30,3990.00,3940.00,2026-09-01,15:00:00";'

    result = parse_sina_quotes(raw, ["sh000001"])

    assert result["sh000001"].name == "上证指数"
    assert result["sh000001"].value == "3986.30"
    assert result["sh000001"].change == "34.12"
    assert result["sh000001"].change_percent == "0.86%"
    assert result["sh000001"].quote_time.utcoffset() == timedelta(hours=8)


def test_parse_sina_quotes_rejects_missing_or_malformed_quote() -> None:
    with pytest.raises(SinaQuoteError, match="行情数据不完整"):
        parse_sina_quotes('var hq_str_sh000001="";', ["sh000001"])


@pytest.mark.asyncio
async def test_sina_client_translates_upstream_failure() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = SinaQuoteClient(transport=httpx.MockTransport(handler))
    with pytest.raises(SinaQuoteError, match="新浪行情服务暂不可用"):
        await client.fetch(["sh000001"])
