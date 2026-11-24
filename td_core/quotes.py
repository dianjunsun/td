"""行情源。免费 A 股源先可用，收费源按同样接口接上。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from td_core.num import D, px as round_px

CN = timezone(timedelta(hours=8))
EAST_FIELDS = "f43,f44,f45,f46,f47,f48,f57,f58,f60,f86"


class QuoteError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class Bar:
    trade_date: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None = None
    amount: Decimal | None = None
    avg: Decimal | None = None

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date,
            "open": _num(self.open),
            "high": _num(self.high),
            "low": _num(self.low),
            "close": _num(self.close),
            "volume": _num(self.volume),
            "amount": _num(self.amount),
            "avg": _num(self.avg),
        }


@dataclass(frozen=True)
class DailySeries:
    adjust: str
    bars: list[Bar]


@dataclass(frozen=True)
class ChartSeries:
    period: str
    label: str
    adjust: str
    prev_close: Decimal | None
    bars: list[Bar]

    def to_dict(self) -> dict:
        return {
            "period": self.period,
            "label": self.label,
            "adjust": self.adjust,
            "prev_close": _num(self.prev_close),
            "bars": [bar.to_dict() for bar in self.bars],
        }


CHART_PERIODS = {
    "intraday": "分时",
    "intraday5": "五日",
    "day": "日K",
    "week": "周K",
    "month": "月K",
}


@dataclass(frozen=True)
class Listing:
    code: str
    market: str
    name: str
    price: Decimal | None = None
    change: Decimal | None = None
    change_pct: Decimal | None = None
    amount: Decimal | None = None
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    prev_close: Decimal | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "market": self.market,
            "symbol": f"{self.code}.{self.market}",
            "name": self.name,
            "price": _num(self.price),
            "change": _num(self.change),
            "change_pct": _num(self.change_pct),
            "amount": _num(self.amount),
            "open": _num(self.open),
            "high": _num(self.high),
            "low": _num(self.low),
            "prev_close": _num(self.prev_close),
        }


@dataclass(frozen=True)
class Quote:
    code: str
    market: str
    name: str
    price: Decimal
    prev_close: Decimal | None
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    vwap: Decimal | None
    as_of: str
    source: str
    source_label: str
    change: Decimal | None = None
    change_pct: Decimal | None = None
    amount: Decimal | None = None

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "market": self.market,
            "symbol": f"{self.code}.{self.market}",
            "name": self.name,
            "price": _plain(self.price),
            "prev_close": _plain(self.prev_close),
            "open": _plain(self.open),
            "high": _plain(self.high),
            "low": _plain(self.low),
            "vwap": _plain(self.vwap),
            "change": _plain(self.change),
            "change_pct": _plain(self.change_pct),
            "amount": _plain(self.amount),
            "as_of": self.as_of,
            "source": self.source,
            "source_label": self.source_label,
        }


def normalize(code: str) -> tuple[str, str]:
    raw = code.strip().upper().replace(" ", "")
    market = ""
    for suffix, name in ((".SH", "SH"), (".SS", "SH"), (".SZ", "SZ"), (".BJ", "BJ")):
        if raw.endswith(suffix):
            market, raw = name, raw[: -len(suffix)]
            break
    if raw.startswith(("SH", "SZ", "BJ")) and raw[2:].isdigit():
        market, raw = raw[:2], raw[2:]
    if not raw.isdigit() or len(raw) != 6:
        raise QuoteError("请使用 6 位 A 股代码，例如 600519")
    if not market:
        if raw.startswith(("5", "6", "9")):
            market = "SH"
        elif raw.startswith(("4", "8")):
            market = "BJ"
        else:
            market = "SZ"
    return raw, market


def http_get(url: str, headers: dict[str, str] | None = None, timeout: float = 8) -> bytes:
    request = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise QuoteError(f"行情请求失败：{reason}") from exc


def http_post(url: str, payload: dict, headers: dict[str, str] | None = None, timeout: float = 8) -> bytes:
    data = json.dumps(payload).encode()
    merged = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(url, data=data, headers=merged)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", None) or exc
        raise QuoteError(f"行情请求失败：{reason}") from exc


class EastMoneyProvider:
    name = "eastmoney"
    label = "东方财富"
    supports_search = True
    supports_board = True

    def quote(self, code: str) -> Quote:
        symbol, market = normalize(code)
        secid = f"{1 if market == 'SH' else 0}.{symbol}"
        url = (
            "http://push2.eastmoney.com/api/qt/stock/get"
            f"?fltt=2&invt=2&secid={secid}&fields={EAST_FIELDS}"
        )
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QuoteError("东方财富返回的不是行情") from exc
        return quote_from_eastmoney(payload.get("data"), symbol, market)

    def search(self, query: str) -> list[Listing]:
        text = query.strip()
        if not text:
            raise QuoteError("请输入代码或名称")
        url = "https://searchapi.eastmoney.com/api/suggest/get?input=" + urllib.parse.quote(text) + "&type=14&count=8"
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QuoteError("东方财富返回的不是搜索结果") from exc
        table = (payload.get("QuotationCodeTable") or {}).get("Data") or []
        return listings_from_eastmoney_search(table)

    def board(self, sort: str) -> list[Listing]:
        order, field = _board_sort(sort)
        url = (
            "http://push2.eastmoney.com/api/qt/clist/get?pn=1&pz=20&po="
            f"{order}&np=1&fltt=2&invt=2&fid={field}"
            "&fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"
            "&fields=f2,f3,f4,f6,f12,f14,f15,f16,f17,f18"
        )
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QuoteError("东方财富返回的不是榜单") from exc
        rows = ((payload.get("data") or {}).get("diff")) or []
        return [listing_from_eastmoney_row(row) for row in rows if row.get("f12")]

    def quotes(self, codes: list[str]) -> list[Listing]:
        secids = []
        for code in codes:
            symbol, market = normalize(code)
            secids.append(f"{1 if market == 'SH' else 0}.{symbol}")
        if not secids:
            return []
        url = (
            "http://push2.eastmoney.com/api/qt/ulist.np/get?fltt=2&secids="
            + ",".join(secids)
            + "&fields=f2,f3,f4,f6,f12,f14,f15,f16,f17,f18"
        )
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QuoteError("东方财富返回的不是行情") from exc
        rows = ((payload.get("data") or {}).get("diff")) or []
        return [listing_from_eastmoney_row(row) for row in rows if row.get("f12")]

    def chart(self, code: str, period: str) -> ChartSeries:
        _period(period)
        if period in ("intraday", "intraday5"):
            return self._trends(code, 5 if period == "intraday5" else 1)
        symbol, market = normalize(code)
        secid = f"{1 if market == 'SH' else 0}.{symbol}"
        klt = {"day": 101, "week": 102, "month": 103}[period]
        limit = {"day": 800, "week": 400, "month": 240}[period]
        query = (
            "fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57"
            "&beg=0&end=20500101&ut=fa5fd1943c7b386f172d6893dbfba10b&rtntype=6"
            f"&secid={secid}&klt={klt}&fqt=1&lmt={limit}"
        )
        for host in ("https://push2his.eastmoney.com", "http://push2his.eastmoney.com"):
            try:
                body = http_get(
                    f"{host}/api/qt/stock/kline/get?{query}",
                    {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
                )
                payload = json.loads(body.decode("utf-8"))
                bars = bars_from_eastmoney((payload.get("data") or {}).get("klines") or [])
                if not bars:
                    raise QuoteError("没有K线")
                return ChartSeries(period, CHART_PERIODS[period], "前复权", None, bars[-limit:])
            except (QuoteError, json.JSONDecodeError):
                continue
        raise QuoteError("东方财富K线暂时取不到")

    def _trends(self, code: str, days: int) -> ChartSeries:
        symbol, market = normalize(code)
        secid = f"{1 if market == 'SH' else 0}.{symbol}"
        url = (
            "http://push2.eastmoney.com/api/qt/stock/trends2/get"
            "?fields1=f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
            "&fields2=f51,f52,f53,f54,f55,f56,f57,f58&iscr=0"
            f"&ndays={days}&secid={secid}"
        )
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"})
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QuoteError("东方财富返回的不是分时") from exc
        data = payload.get("data") or {}
        bars = bars_from_eastmoney_trends(data.get("trends") or [])
        if not bars:
            raise QuoteError("没有分时")
        period = "intraday5" if days > 1 else "intraday"
        return ChartSeries(period, CHART_PERIODS[period], "", _price(data.get("preClose")), bars)


class SinaProvider:
    name = "sina"
    label = "新浪财经"
    supports_search = True
    supports_board = False

    def quote(self, code: str) -> Quote:
        symbol, market = normalize(code)
        url = f"https://hq.sinajs.cn/list={market.lower()}{symbol}"
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
        text = body.decode("gb18030", errors="replace")
        return quote_from_sina(text, symbol, market)

    def search(self, query: str) -> list[Listing]:
        text = query.strip()
        if not text:
            raise QuoteError("请输入代码或名称")
        try:
            symbol, market = normalize(text)
            quote = self.quote(symbol)
            return [listing_from_quote(quote)]
        except QuoteError:
            pass
        url = "https://suggest3.sinajs.cn/suggest/type=11,12,13,14,15&key=" + urllib.parse.quote(text)
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
        found = listings_from_sina_suggest(body.decode("gb18030", errors="replace"))
        if not found:
            raise QuoteError("没有匹配的股票")
        return found[:8]

    def quotes(self, codes: list[str]) -> list[Listing]:
        symbols = []
        for code in codes:
            symbol, market = normalize(code)
            symbols.append(f"{market.lower()}{symbol}")
        if not symbols:
            return []
        url = "https://hq.sinajs.cn/list=" + ",".join(symbols)
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
        return listings_from_sina_blob(body.decode("gb18030", errors="replace"))

    def chart(self, code: str, period: str) -> ChartSeries:
        _period(period)
        symbol, market = normalize(code)
        scale, length = {
            "intraday": (1, 300),
            "intraday5": (5, 240),
            "day": (240, 800),
            "week": (1200, 400),
            "month": (7200, 240),
        }[period]
        symbol_param = f"{market.lower()}{symbol}"
        if period == "intraday":
            url = (
                "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
                f"?symbol={symbol_param}&scale={scale}&ma=no&datalen={length}"
            )
        else:
            url = (
                "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
                f"?symbol={symbol_param}&scale={scale}&ma=no&datalen={length}"
            )
        body = http_get(url, {"User-Agent": "Mozilla/5.0", "Referer": "https://finance.sina.com.cn"})
        if body.strip() in (b"", b"null"):
            raise QuoteError("没有K线")
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QuoteError("新浪财经返回的不是K线") from exc
        bars = fill_avg(bars_from_sina(payload))
        if period == "intraday" and bars:
            last_day = bars[-1].trade_date[:10]
            bars = [bar for bar in bars if bar.trade_date[:10] == last_day]
        if not bars:
            raise QuoteError("没有K线")
        return ChartSeries(period, CHART_PERIODS[period], "" if period.startswith("intraday") else "不复权", None, bars[-length:])


class TushareProvider:
    """收费会员接口。未配置 TUSHARE_TOKEN 时不会进入默认行情链。"""

    name = "tushare"
    label = "Tushare"
    supports_search = True
    supports_board = False

    def __init__(self, token: str):
        self.token = token

    def quote(self, code: str) -> Quote:
        symbol, market = normalize(code)
        ts_code = f"{symbol}.{market}"
        errors: list[str] = []
        for api_name in ("rt_k", "daily"):
            try:
                payload = self._call(api_name, {"ts_code": ts_code})
                found = quote_from_tushare(payload, symbol, market, api_name)
                if found is not None:
                    return found
            except QuoteError as exc:
                errors.append(exc.message)
        raise QuoteError("；".join(errors) or "Tushare 没有这只股票")

    def search(self, query: str) -> list[Listing]:
        text = query.strip()
        if not text:
            raise QuoteError("请输入代码或名称")
        try:
            symbol, market = normalize(text)
            return [Listing(code=symbol, market=market, name=symbol)]
        except QuoteError:
            pass
        payload = self._call("stock_basic", {"name": text, "list_status": "L"})
        return listings_from_tushare_basic(payload)

    def chart(self, code: str, period: str) -> ChartSeries:
        _period(period)
        if period.startswith("intraday"):
            raise QuoteError("Tushare 没有分时")
        symbol, market = normalize(code)
        api_name = {"day": "daily", "week": "weekly", "month": "monthly"}[period]
        days = {"day": 1400, "week": 2200, "month": 5000}[period]
        start = (datetime.now(CN) - timedelta(days=days)).strftime("%Y%m%d")
        payload = self._call(api_name, {"ts_code": f"{symbol}.{market}", "start_date": start})
        bars = bars_from_tushare(payload)
        if not bars:
            raise QuoteError("没有K线")
        return ChartSeries(period, CHART_PERIODS[period], "不复权", None, bars[-800:])

    def _call(self, api_name: str, params: dict) -> dict:
        body = http_post(
            "https://api.tushare.pro",
            {"api_name": api_name, "token": self.token, "params": params, "fields": ""},
        )
        try:
            payload = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QuoteError("Tushare 返回的不是行情") from exc
        if payload.get("code") not in (0, None):
            raise QuoteError(str(payload.get("msg") or "Tushare 拒绝了请求"))
        return payload


class UnavailableProvider:
    def __init__(self, name: str, label: str, note: str):
        self.name = name
        self.label = label
        self.note = note
        self.ready = False

    def quote(self, code: str) -> Quote:
        raise QuoteError(self.note)


class QuoteRouter:
    def __init__(self, providers: list):
        if not providers:
            raise QuoteError("没有配置行情源")
        self.providers = providers

    def quote(self, code: str, source: str) -> Quote:
        chosen = source.strip()
        if not chosen:
            raise QuoteError("请选择行情源")
        provider = next((item for item in self.providers if item.name == chosen), None)
        if provider is None:
            labels = "、".join(item.label for item in self.providers)
            raise QuoteError(f"未知行情源，可选 {labels}")
        return provider.quote(code)

    def search(self, query: str, source: str) -> list[Listing]:
        provider = self._provider(source)
        search = getattr(provider, "search", None)
        if not getattr(provider, "supports_search", False) or search is None:
            raise QuoteError(f"{provider.label}不能按名称搜索")
        return search(query)

    def board(self, source: str, sort: str) -> list[Listing]:
        provider = self._provider(source)
        board = getattr(provider, "board", None)
        if not getattr(provider, "supports_board", False) or board is None:
            raise QuoteError(f"{provider.label}没有涨跌榜，请用代码或名称搜索")
        return board(sort)

    def chart(self, source: str, code: str, period: str) -> ChartSeries:
        _period(period)
        provider = self._provider(source)
        if getattr(provider, "ready", True) is False:
            raise QuoteError(getattr(provider, "note", "") or f"{provider.label}没有K线")
        method = getattr(provider, "chart", None)
        if method is None:
            raise QuoteError(f"{provider.label}没有K线")
        return method(code, period)

    def daily(self, source: str, code: str) -> DailySeries:
        series = self.chart(source, code, "day")
        return DailySeries(series.adjust, series.bars)

    def quotes(self, source: str, codes: list[str]) -> list[Listing]:
        provider = self._provider(source)
        batch = getattr(provider, "quotes", None)
        if batch is None:
            return [listing_from_quote(provider.quote(code)) for code in codes]
        return batch(codes)

    def _provider(self, source: str):
        chosen = source.strip()
        if not chosen:
            raise QuoteError("请选择行情源")
        provider = next((item for item in self.providers if item.name == chosen), None)
        if provider is None:
            labels = "、".join(item.label for item in self.providers)
            raise QuoteError(f"未知行情源，可选 {labels}")
        return provider

    def describe(self) -> list[dict]:
        return [
            {
                "id": provider.name,
                "label": provider.label,
                "ready": getattr(provider, "ready", True),
                "note": getattr(provider, "note", ""),
                "search": getattr(provider, "supports_search", False),
                "board": getattr(provider, "supports_board", False),
            }
            for provider in self.providers
        ]


def build_router() -> QuoteRouter:
    providers: list = [EastMoneyProvider(), SinaProvider()]
    token = os.environ.get("TUSHARE_TOKEN", "").strip()
    if token:
        providers.append(TushareProvider(token))
    else:
        providers.append(UnavailableProvider("tushare", "Tushare", "要使用 Tushare，请先设置 TUSHARE_TOKEN"))
    return QuoteRouter(providers)


def quote_from_eastmoney(data: dict | None, code: str, market: str) -> Quote:
    if not data or data.get("f43") in (None, "", "-"):
        raise QuoteError("没有这只股票")
    price = _price(data.get("f43"))
    if price is None:
        raise QuoteError("没有最新价")
    volume = _price(data.get("f47"))
    amount = _price(data.get("f48"))
    prev_close = _price(data.get("f60"))
    change, change_pct = _move(price, prev_close)
    return Quote(
        code=str(data.get("f57") or code),
        market=market,
        name=str(data.get("f58") or code),
        price=price,
        prev_close=prev_close,
        open=_price(data.get("f46")),
        high=_price(data.get("f44")),
        low=_price(data.get("f45")),
        vwap=_vwap(price, volume, amount, volume_unit="hand", amount_unit="yuan"),
        as_of=_from_unix(data.get("f86")),
        source="eastmoney",
        source_label="东方财富",
        change=change,
        change_pct=change_pct,
        amount=amount,
    )


def quote_from_sina(text: str, code: str, market: str) -> Quote:
    start = text.find('"')
    end = text.rfind('"')
    if start < 0 or end <= start:
        raise QuoteError("没有这只股票")
    parts = text[start + 1 : end].split(",")
    if len(parts) < 10 or not parts[3]:
        raise QuoteError("没有这只股票")
    price = _price(parts[3])
    if price is None:
        raise QuoteError("没有最新价")
    volume = _price(parts[8])
    amount = _price(parts[9])
    prev_close = _price(parts[2])
    change, change_pct = _move(price, prev_close)
    as_of = " ".join(part for part in (parts[30] if len(parts) > 30 else "", parts[31] if len(parts) > 31 else "") if part)
    return Quote(
        code=code,
        market=market,
        name=parts[0] or code,
        price=price,
        prev_close=prev_close,
        open=_price(parts[1]),
        high=_price(parts[4]),
        low=_price(parts[5]),
        vwap=_vwap(price, volume, amount, volume_unit="share", amount_unit="yuan"),
        as_of=as_of or _now(),
        source="sina",
        source_label="新浪财经",
        change=change,
        change_pct=change_pct,
        amount=amount,
    )


def quote_from_tushare(payload: dict, code: str, market: str, api_name: str) -> Quote | None:
    data = payload.get("data") or {}
    fields = data.get("fields") or []
    items = data.get("items") or []
    if not items:
        return None
    rows = [dict(zip(fields, item)) for item in items]
    rows.sort(key=lambda row: str(row.get("trade_time") or row.get("trade_date") or ""))
    row = rows[-1]
    price = _price(row.get("close") or row.get("price"))
    if price is None:
        raise QuoteError("没有最新价")
    volume = _price(row.get("vol"))
    amount = _price(row.get("amount"))
    amount_unit = "thousand" if api_name == "daily" else "yuan"
    yuan = None if amount is None else amount * (Decimal(1000) if amount_unit == "thousand" else Decimal(1))
    prev_close = _price(row.get("pre_close"))
    change, change_pct = _move(price, prev_close)
    stamp = str(row.get("trade_time") or row.get("trade_date") or _now())
    return Quote(
        code=code,
        market=market,
        name=str(row.get("name") or code),
        price=price,
        prev_close=prev_close,
        open=_price(row.get("open")),
        high=_price(row.get("high")),
        low=_price(row.get("low")),
        vwap=_vwap(price, volume, amount, volume_unit="hand", amount_unit=amount_unit),
        as_of=stamp,
        source="tushare",
        source_label="Tushare",
        change=change,
        change_pct=change_pct,
        amount=yuan,
    )


def _vwap(price: Decimal, volume: Decimal | None, amount: Decimal | None, volume_unit: str, amount_unit: str) -> Decimal | None:
    if volume is None or amount is None or volume == 0:
        return None
    yuan = amount * (Decimal(1000) if amount_unit == "thousand" else Decimal(1))
    shares = volume * (Decimal(100) if volume_unit == "hand" else Decimal(1))
    if shares == 0:
        return None
    return round_px(yuan / shares)


def _price(value) -> Decimal | None:
    if value is None or value == "" or value == "-":
        return None
    number = D(value)
    if number <= 0:
        return None
    return number


def _plain(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(D(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _from_unix(value) -> str:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return _now()
    return datetime.fromtimestamp(stamp, CN).strftime("%Y-%m-%d %H:%M:%S")


def _now() -> str:
    return datetime.now(CN).strftime("%Y-%m-%d %H:%M:%S")


def listing_from_quote(quote: Quote) -> Listing:
    return Listing(
        code=quote.code,
        market=quote.market,
        name=quote.name,
        price=quote.price,
        change=quote.change,
        change_pct=quote.change_pct,
        amount=quote.amount,
        open=quote.open,
        high=quote.high,
        low=quote.low,
        prev_close=quote.prev_close,
    )


def _move(price: Decimal, prev: Decimal | None) -> tuple[Decimal | None, Decimal | None]:
    if prev is None or prev == 0:
        return None, None
    change = price - prev
    return change, change / prev


def listing_from_eastmoney_row(row: dict) -> Listing:
    code, market = normalize(str(row.get("f12") or ""))
    percent = _signed(row.get("f3"))
    return Listing(
        code=code,
        market=market,
        name=str(row.get("f14") or code),
        price=_price(row.get("f2")),
        change=_signed(row.get("f4")),
        change_pct=None if percent is None else percent / Decimal(100),
        amount=_price(row.get("f6")),
        open=_price(row.get("f17")),
        high=_price(row.get("f15")),
        low=_price(row.get("f16")),
        prev_close=_price(row.get("f18")),
    )


def listings_from_eastmoney_search(rows: list) -> list[Listing]:
    found: list[Listing] = []
    for row in rows:
        if row.get("Classify") not in (None, "", "AStock", "Fund"):
            continue
        try:
            code, market = normalize(str(row.get("Code") or ""))
        except QuoteError:
            continue
        found.append(Listing(code=code, market=market, name=str(row.get("Name") or code)))
    if not found:
        raise QuoteError("没有匹配的股票")
    return found[:8]


def listings_from_sina_suggest(text: str) -> list[Listing]:
    start = text.find('"')
    end = text.rfind('"')
    if start < 0 or end <= start:
        return []
    found: list[Listing] = []
    for record in text[start + 1 : end].split(";"):
        parts = record.split(",")
        if len(parts) < 4:
            continue
        try:
            code, market = normalize(parts[2])
        except QuoteError:
            continue
        found.append(Listing(code=code, market=market, name=parts[4] or parts[0] or code))
    return found


def listings_from_sina_blob(text: str) -> list[Listing]:
    found: list[Listing] = []
    for chunk in text.split("var hq_str_")[1:]:
        head, _, _rest = chunk.partition("=")
        symbol = head.strip()
        if len(symbol) < 8:
            continue
        try:
            quote = quote_from_sina(f"var hq_str_{chunk}", symbol[2:], symbol[:2].upper())
        except QuoteError:
            continue
        found.append(listing_from_quote(quote))
    return found


def listings_from_tushare_basic(payload: dict) -> list[Listing]:
    data = payload.get("data") or {}
    fields = data.get("fields") or []
    found: list[Listing] = []
    for item in data.get("items") or []:
        row = dict(zip(fields, item))
        try:
            code, market = normalize(str(row.get("ts_code") or ""))
        except QuoteError:
            continue
        found.append(Listing(code=code, market=market, name=str(row.get("name") or code)))
    if not found:
        raise QuoteError("没有匹配的股票")
    return found[:8]


def _period(period: str) -> str:
    if period not in CHART_PERIODS:
        names = "、".join(CHART_PERIODS.values())
        raise QuoteError(f"未知周期，可选 {names}")
    return period


def bars_from_eastmoney(rows: list) -> list[Bar]:
    bars: list[Bar] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 6:
            continue
        # 日期,开盘,收盘,最高,最低,成交量,成交额
        bar = _bar(
            parts[0], parts[1], parts[3], parts[4], parts[2],
            volume=parts[5] if len(parts) > 5 else None,
            amount=parts[6] if len(parts) > 6 else None,
        )
        if bar is not None:
            bars.append(bar)
    return bars


def bars_from_eastmoney_trends(rows: list) -> list[Bar]:
    bars: list[Bar] = []
    for row in rows:
        parts = str(row).split(",")
        if len(parts) < 5:
            continue
        # 时间,开盘,收盘,最高,最低,成交量,成交额,均价
        bar = _bar(
            parts[0], parts[1], parts[3] if len(parts) > 4 else parts[1], parts[4] if len(parts) > 4 else parts[1], parts[2],
            volume=parts[5] if len(parts) > 5 else None,
            amount=parts[6] if len(parts) > 6 else None,
            avg=parts[7] if len(parts) > 7 else None,
        )
        if bar is not None:
            bars.append(bar)
    return bars


def bars_from_sina(rows: list) -> list[Bar]:
    bars: list[Bar] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        bar = _bar(
            str(row.get("day") or ""), row.get("open"), row.get("high"), row.get("low"), row.get("close"),
            volume=row.get("volume"), amount=row.get("amount"),
        )
        if bar is not None:
            bars.append(bar)
    return bars


def fill_avg(bars: list[Bar]) -> list[Bar]:
    filled: list[Bar] = []
    day = ""
    volume = Decimal(0)
    amount = Decimal(0)
    for bar in bars:
        if bar.avg is not None:
            filled.append(bar)
            continue
        key = bar.trade_date[:10]
        if key != day:
            day, volume, amount = key, Decimal(0), Decimal(0)
        if bar.volume is None or bar.amount is None:
            filled.append(bar)
            continue
        volume += bar.volume
        amount += bar.amount
        avg = round_px(amount / volume) if volume else None
        filled.append(Bar(bar.trade_date, bar.open, bar.high, bar.low, bar.close, bar.volume, bar.amount, avg))
    return filled


def bars_from_tushare(payload: dict) -> list[Bar]:
    data = payload.get("data") or {}
    fields = data.get("fields") or []
    bars: list[Bar] = []
    for item in data.get("items") or []:
        row = dict(zip(fields, item))
        stamp = str(row.get("trade_date") or "")
        if len(stamp) == 8 and stamp.isdigit():
            stamp = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:]}"
        bar = _bar(stamp, row.get("open"), row.get("high"), row.get("low"), row.get("close"))
        if bar is not None:
            bars.append(bar)
    bars.sort(key=lambda bar: bar.trade_date)
    return bars


def _bar(trade_date: str, open_, high, low, close, volume=None, amount=None, avg=None) -> Bar | None:
    opened = _price(open_)
    top = _price(high)
    bottom = _price(low)
    settled = _price(close)
    if not trade_date or opened is None or top is None or bottom is None or settled is None:
        return None
    return Bar(
        trade_date=trade_date, open=opened, high=top, low=bottom, close=settled,
        volume=_size(volume), amount=_size(amount), avg=_price(avg),
    )


def _size(value) -> Decimal | None:
    if value is None or value == "" or value == "-":
        return None
    number = D(value)
    if number < 0:
        return None
    return number


def _board_sort(sort: str) -> tuple[str, str]:
    if sort == "gainers":
        return "1", "f3"
    if sort == "losers":
        return "0", "f3"
    if sort == "amount":
        return "1", "f6"
    raise QuoteError("未知榜单")


def _signed(value) -> Decimal | None:
    if value is None or value == "" or value == "-":
        return None
    return D(value)


def _num(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)
