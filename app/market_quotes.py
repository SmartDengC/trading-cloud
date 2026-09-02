from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from time import monotonic, perf_counter
from zoneinfo import ZoneInfo

import httpx

SINA_QUOTES_URL = "https://hq.sinajs.cn/list={symbols}"
SINA_REFERER = "https://finance.sina.com.cn/"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
SINA_CACHE_TTL_SECONDS = 5.0
SINA_MAX_URL_LENGTH = 1800
logger = logging.getLogger("trading.market_quotes")


class SinaQuoteError(Exception):
    pass


@dataclass(frozen=True)
class SinaQuote:
    name: str
    value: str
    change: str | None
    change_percent: str | None
    quote_time: datetime


def _decimal(value: str) -> Decimal | None:
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        return None
    except ValueError:
        return None
    return number if number.is_finite() else None


def _format_decimal(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _quote_time(
    fields: list[str], date_index: int | None = None, time_index: int | None = None
) -> datetime:
    if date_index is None:
        for index, value in enumerate(fields):
            if re.fullmatch(r"\d{4}[-/]\d{2}[-/]\d{2}", value.strip()):
                date_index = index
                break
    if date_index is None:
        raise SinaQuoteError("行情数据不完整")
    if time_index is None:
        time_index = date_index + 1
    if time_index >= len(fields):
        raise SinaQuoteError("行情数据不完整")
    date_value = fields[date_index].strip().replace("/", "-")
    time_value = fields[time_index].strip()
    if re.fullmatch(r"\d{2}:\d{2}", time_value):
        time_value += ":00"
    try:
        return datetime.strptime(
            f"{date_value} {time_value}", "%Y-%m-%d %H:%M:%S"
        ).replace(tzinfo=SHANGHAI_TZ)
    except ValueError as error:
        raise SinaQuoteError("行情时间格式不合法") from error


def parse_sina_quotes(raw: str, symbols: list[str]) -> dict[str, SinaQuote]:
    result: dict[str, SinaQuote] = {}
    pattern = re.compile(r'var hq_str_([A-Za-z0-9_.-]+)="(.*?)";')
    payloads = {symbol: value for symbol, value in pattern.findall(raw)}
    for symbol in symbols:
        payload = payloads.get(symbol, "")
        fields = [item.strip() for item in payload.split(",")]
        if not payload or len(fields) < 4 or not fields[0]:
            raise SinaQuoteError("行情数据不完整")
        if symbol.lower().startswith("hf_"):
            current = _decimal(fields[0])
            previous = _decimal(fields[7]) if len(fields) > 7 else None
            name = fields[13] if len(fields) > 13 and fields[13] else symbol
            quote_time = _quote_time(fields, date_index=12, time_index=6)
        elif symbol.lower().startswith("hk"):
            previous = _decimal(fields[3])
            current = _decimal(fields[6])
            name = fields[1] if len(fields) > 1 and fields[1] else fields[0]
            quote_time = _quote_time(fields)
        else:
            previous = _decimal(fields[2])
            current = _decimal(fields[3])
            name = fields[0]
            quote_time = _quote_time(fields)
        if current is None:
            raise SinaQuoteError("行情数据不完整")
        if previous is None:
            change = None
            change_percent = None
        else:
            change = current - previous
            change_percent = change / previous * 100 if previous != 0 else None
        result[symbol] = SinaQuote(
            name=name,
            value=_format_decimal(current),
            change=_format_decimal(change) if change is not None else None,
            change_percent=f"{change_percent:.2f}%" if change_percent is not None else None,
            quote_time=quote_time,
        )
    return result


class SinaQuoteClient:
    def __init__(
        self,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_ttl: float = SINA_CACHE_TTL_SECONDS,
    ) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=1.0, read=2.5, write=2.5, pool=1.0),
            transport=transport,
            headers={"Referer": SINA_REFERER, "User-Agent": "market-diary/1.0"},
        )
        self._cache_ttl = cache_ttl
        self._cache: dict[tuple[str, ...], tuple[float, dict[str, SinaQuote]]] = {}
        self._inflight: dict[tuple[str, ...], asyncio.Task[dict[str, SinaQuote]]] = {}

    async def close(self) -> None:
        await self._client.aclose()

    async def fetch(self, symbols: list[str]) -> dict[str, SinaQuote]:
        if not symbols:
            return {}
        key = tuple(dict.fromkeys(symbols))
        cached = self._cache.get(key)
        if cached and monotonic() - cached[0] < self._cache_ttl:
            logger.info("sina_quotes cache_hit symbols=%d", len(key))
            return cached[1]

        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._fetch_uncached(key))
            self._inflight[key] = task
            task.add_done_callback(
                lambda done: self._inflight.pop(key, None)
                if self._inflight.get(key) is done
                else None
            )
        return await asyncio.shield(task)

    async def _fetch_uncached(self, symbols: tuple[str, ...]) -> dict[str, SinaQuote]:
        started = perf_counter()
        batches = _split_symbols(symbols)
        results = await asyncio.gather(
            *(self._fetch_batch(batch) for batch in batches), return_exceptions=True
        )
        quotes: dict[str, SinaQuote] = {}
        errors: list[str] = []
        for result in results:
            if isinstance(result, BaseException):
                errors.append(str(result))
            else:
                quotes.update(result)
        duration_ms = (perf_counter() - started) * 1000
        logger.info(
            "sina_quotes upstream_complete symbols=%d batches=%d success=%d duration_ms=%.2f errors=%s",
            len(symbols),
            len(batches),
            len(quotes),
            duration_ms,
            errors or "none",
        )
        if not quotes:
            raise SinaQuoteError(errors[0] if errors else "新浪行情数据解析失败")
        self._cache[symbols] = (monotonic(), quotes)
        return quotes

    async def _fetch_batch(self, symbols: tuple[str, ...]) -> dict[str, SinaQuote]:
        started = perf_counter()
        try:
            response = await self._client.get(SINA_QUOTES_URL.format(symbols=",".join(symbols)))
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            logger.warning(
                "sina_quotes upstream_error symbols=%d status=%d duration_ms=%.2f",
                len(symbols),
                error.response.status_code,
                (perf_counter() - started) * 1000,
            )
            raise SinaQuoteError("新浪行情服务暂不可用") from error
        except (httpx.HTTPError, TimeoutError) as error:
            logger.warning(
                "sina_quotes upstream_error symbols=%d status=network_error duration_ms=%.2f",
                len(symbols),
                (perf_counter() - started) * 1000,
            )
            raise SinaQuoteError("新浪行情服务暂不可用") from error
        try:
            raw = response.content.decode(response.encoding or "gbk", errors="replace")
            result = _parse_available_quotes(raw, symbols)
            if not result:
                raise SinaQuoteError("新浪行情数据解析失败")
            logger.debug(
                "sina_quotes batch_complete symbols=%d success=%d duration_ms=%.2f",
                len(symbols),
                len(result),
                (perf_counter() - started) * 1000,
            )
            return result
        except SinaQuoteError:
            raise
        except Exception as error:
            raise SinaQuoteError("新浪行情数据解析失败") from error


def _parse_available_quotes(raw: str, symbols: tuple[str, ...]) -> dict[str, SinaQuote]:
    result: dict[str, SinaQuote] = {}
    for symbol in symbols:
        try:
            result.update(parse_sina_quotes(raw, [symbol]))
        except SinaQuoteError:
            continue
    return result


def _split_symbols(symbols: tuple[str, ...]) -> list[tuple[str, ...]]:
    batches: list[tuple[str, ...]] = []
    current: list[str] = []
    prefix_length = len(SINA_QUOTES_URL) - len("{symbols}")
    current_length = prefix_length
    for symbol in symbols:
        symbol_length = len(symbol) + (1 if current else 0)
        if current and current_length + symbol_length > SINA_MAX_URL_LENGTH:
            batches.append(tuple(current))
            current = []
            current_length = prefix_length
            symbol_length = len(symbol)
        current.append(symbol)
        current_length += symbol_length
    if current:
        batches.append(tuple(current))
    return batches
