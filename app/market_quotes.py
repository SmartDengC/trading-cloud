from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx

SINA_QUOTES_URL = "https://hq.sinajs.cn/list={symbols}"
SINA_REFERER = "https://finance.sina.com.cn/"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


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


def _quote_time(fields: list[str]) -> datetime:
    date_index = None
    for index, value in enumerate(fields):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value.strip()):
            date_index = index
            break
    if date_index is None or date_index + 1 >= len(fields):
        raise SinaQuoteError("行情数据不完整")
    try:
        return datetime.strptime(
            f"{fields[date_index].strip()} {fields[date_index + 1].strip()}", "%Y-%m-%d %H:%M:%S"
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
            current = _decimal(fields[1])
            previous = _decimal(fields[7]) if len(fields) > 7 else None
        else:
            previous = _decimal(fields[2])
            current = _decimal(fields[3])
        if current is None:
            raise SinaQuoteError("行情数据不完整")
        if previous is None:
            change = None
            change_percent = None
        else:
            change = current - previous
            change_percent = change / previous * 100 if previous != 0 else None
        result[symbol] = SinaQuote(
            name=fields[0],
            value=_format_decimal(current),
            change=_format_decimal(change) if change is not None else None,
            change_percent=f"{change_percent:.2f}%" if change_percent is not None else None,
            quote_time=_quote_time(fields),
        )
    return result


class SinaQuoteClient:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def fetch(self, symbols: list[str]) -> dict[str, SinaQuote]:
        if not symbols:
            return {}
        try:
            async with httpx.AsyncClient(
                timeout=3,
                transport=self._transport,
                headers={"Referer": SINA_REFERER, "User-Agent": "market-diary/1.0"},
            ) as client:
                response = await client.get(SINA_QUOTES_URL.format(symbols=",".join(symbols)))
                response.raise_for_status()
        except (httpx.HTTPError, TimeoutError) as error:
            raise SinaQuoteError("新浪行情服务暂不可用") from error
        try:
            raw = response.content.decode(response.encoding or "gbk", errors="replace")
            result: dict[str, SinaQuote] = {}
            for symbol in symbols:
                try:
                    result.update(parse_sina_quotes(raw, [symbol]))
                except SinaQuoteError:
                    continue
            if not result:
                raise SinaQuoteError("新浪行情数据解析失败")
            return result
        except SinaQuoteError:
            raise
        except Exception as error:
            raise SinaQuoteError("新浪行情数据解析失败") from error
