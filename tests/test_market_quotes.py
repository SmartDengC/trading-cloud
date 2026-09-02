import asyncio
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


def test_parse_sina_quotes_normalizes_hong_kong_index() -> None:
    raw = (
        'var hq_str_hkHSTECH="HSTECH,恒生科技指数,4532.220,4550.880,4532.220,4460.130,'
        '4480.670,-70.210,-1.543,0.00000,0.00000,28278487,644349865,0.000,0.000,'
        '6715.460,4229.940,2026/09/02,12:05";'
    )

    result = parse_sina_quotes(raw, ["hkHSTECH"])

    assert result["hkHSTECH"].name == "恒生科技指数"
    assert result["hkHSTECH"].value == "4480.67"
    assert result["hkHSTECH"].change == "-70.21"
    assert result["hkHSTECH"].change_percent == "-1.54%"
    assert result["hkHSTECH"].quote_time.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-02 12:05:00"


def test_parse_sina_quotes_normalizes_international_spot_quote() -> None:
    raw = (
        'var hq_str_hf_XAU="4303.60,4328.080,4303.60,4303.95,4335.52,4282.52,12:26:00,'
        '4328.08,4331.05,0,0,0,2026-09-02,伦敦金（现货黄金）";'
    )

    result = parse_sina_quotes(raw, ["hf_XAU"])

    assert result["hf_XAU"].name == "伦敦金（现货黄金）"
    assert result["hf_XAU"].value == "4303.60"
    assert result["hf_XAU"].change == "-24.48"
    assert result["hf_XAU"].change_percent == "-0.57%"
    assert result["hf_XAU"].quote_time.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-02 12:26:00"


def test_parse_sina_quotes_normalizes_brent_quote() -> None:
    raw = (
        'var hq_str_hf_OIL="95.304,,95.310,95.330,97.040,95.140,12:26:38,94.650,95.250,'
        '0,5,2,2026-09-02,布伦特原油,29722";'
    )

    result = parse_sina_quotes(raw, ["hf_OIL"])

    assert result["hf_OIL"].name == "布伦特原油"
    assert result["hf_OIL"].value == "95.30"
    assert result["hf_OIL"].change == "0.65"
    assert result["hf_OIL"].change_percent == "0.69%"
    assert result["hf_OIL"].quote_time.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-02 12:26:38"


def test_parse_sina_quotes_normalizes_us_index() -> None:
    raw = (
        'var hq_str_gb_ixic="纳斯达克,26099.7742,-1.03,2026-09-02 05:30:00,-271.1149,'
        '26031.6697,26260.6818,25995.5300,27190.2070,20690.2500,5809876309,6271106057,'
        '0,0.00,--,0.00,0.00,0.00,0.00,0,0,0.0000,0.00,0.00,,Sep 01 05:16PM EDT,'
        '26370.8891,0,1,2026,0.0000,0.0000,0.0000,0.0000,0.0000,0.0000";'
    )

    result = parse_sina_quotes(raw, ["gb_ixic"])

    assert result["gb_ixic"].name == "纳斯达克"
    assert result["gb_ixic"].value == "26099.77"
    assert result["gb_ixic"].change == "-271.11"
    assert result["gb_ixic"].change_percent == "-1.03%"
    assert result["gb_ixic"].quote_time.strftime("%Y-%m-%d %H:%M:%S") == "2026-09-02 05:30:00"


@pytest.mark.asyncio
async def test_sina_client_translates_upstream_failure() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    client = SinaQuoteClient(transport=httpx.MockTransport(handler))
    with pytest.raises(SinaQuoteError, match="新浪行情服务暂不可用"):
        await client.fetch(["sh000001"])


@pytest.mark.asyncio
async def test_sina_client_reuses_cached_result_for_short_window() -> None:
    calls = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=(
                'var hq_str_sh000001="上证指数,3990.00,3952.18,3986.30,3990.00,3940.00,'
                '2026-09-01,15:00:00";'
            ).encode("gbk"),
        )

    client = SinaQuoteClient(transport=httpx.MockTransport(handler), cache_ttl=5)

    await client.fetch(["sh000001"])
    await client.fetch(["sh000001"])

    assert calls == 1
    await client.close()


@pytest.mark.asyncio
async def test_sina_client_deduplicates_concurrent_requests() -> None:
    calls = 0
    request_started = asyncio.Event()
    release_request = asyncio.Event()

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        request_started.set()
        await release_request.wait()
        return httpx.Response(
            200,
            content=(
                'var hq_str_sh000001="上证指数,3990.00,3952.18,3986.30,3990.00,3940.00,'
                '2026-09-01,15:00:00";'
            ).encode("gbk"),
        )

    client = SinaQuoteClient(transport=httpx.MockTransport(handler), cache_ttl=5)
    first = asyncio.create_task(client.fetch(["sh000001"]))
    await request_started.wait()
    second = asyncio.create_task(client.fetch(["sh000001"]))
    release_request.set()

    await asyncio.gather(first, second)

    assert calls == 1
    await client.close()
