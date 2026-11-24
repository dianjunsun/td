from decimal import Decimal

import pytest

from td_core.quotes import (
    bars_from_eastmoney,
    bars_from_eastmoney_trends,
    bars_from_sina,
    bars_from_tushare,
    fill_avg,
    EastMoneyProvider,
    QuoteError,
    QuoteRouter,
    SinaProvider,
    TushareProvider,
    build_router,
    listing_from_eastmoney_row,
    listings_from_eastmoney_search,
    listings_from_sina_suggest,
    normalize,
    listing_from_quote,
    quote_from_eastmoney,
    quote_from_sina,
    quote_from_tushare,
)


EAST = {
    "f43": 1457.28,
    "f44": 1463.26,
    "f45": 1420.0,
    "f46": 1425.0,
    "f47": 38957,
    "f48": 5634931587.0,
    "f57": "600519",
    "f58": "贵州茅台",
    "f60": 1439.0,
    "f86": 1795503158,
}

_SINA_PARTS = ["贵州茅台", "1425.000", "1439.000", "1457.540", "1463.260", "1420.000", "", "", "3889806", "5626332206.000"]
_SINA_PARTS.extend([""] * 22)
_SINA_PARTS[30] = "2026-11-24"
_SINA_PARTS[31] = "14:52:23"
SINA = 'var hq_str_sh600519="' + ",".join(_SINA_PARTS) + '";'


def test_normalize_accepts_market_suffixes():
    assert normalize("600519") == ("600519", "SH")
    assert normalize("sz000001") == ("000001", "SZ")
    assert normalize("830799.BJ") == ("830799", "BJ")
    with pytest.raises(QuoteError):
        normalize("DEMO")


def test_eastmoney_parser_uses_hand_volume_for_vwap():
    quote = quote_from_eastmoney(EAST, "600519", "SH")
    assert quote.name == "贵州茅台"
    assert quote.price == quote.price
    assert str(quote.price) == "1457.28"
    assert str(quote.vwap) == "1446.4491"
    assert quote.source_label == "东方财富"
    assert quote.as_of.startswith("2026-")


def test_every_source_fills_the_same_quote_fields():
    east = quote_from_eastmoney(EAST, "600519", "SH")
    sina = quote_from_sina(SINA, "600519", "SH")
    payload = {
        "data": {
            "fields": ["trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"],
            "items": [["20261124", 1425, 1463.26, 1420, 1457.28, 1439, 38957, 5634931.587]],
        }
    }
    tushare = quote_from_tushare(payload, "600519", "SH", "daily")
    for quote in (east, sina, tushare):
        assert quote.prev_close is not None
        assert quote.open is not None and quote.high is not None and quote.low is not None
        assert quote.change == quote.price - quote.prev_close
        assert quote.change_pct == quote.change / quote.prev_close
        assert quote.amount is not None and quote.vwap is not None
    assert east.amount == Decimal("5634931587")
    assert sina.amount == Decimal("5626332206")
    assert tushare.amount == Decimal("5634931587")
    listed = listing_from_quote(sina)
    assert listed.change == sina.change
    assert listed.change_pct == sina.change_pct
    assert listed.amount == sina.amount


def test_sina_parser_reads_gbk_fields():
    quote = quote_from_sina(SINA, "600519", "SH")
    assert quote.name == "贵州茅台"
    assert quote.price == Decimal("1457.54")
    assert str(quote.vwap) == "1446.4300"
    assert quote.as_of == "2026-11-24 14:52:23"


def test_tushare_daily_uses_the_latest_bar():
    payload = {
        "code": 0,
        "data": {
            "fields": ["ts_code", "trade_date", "open", "high", "low", "close", "pre_close", "vol", "amount"],
            "items": [
                ["600519.SH", "20261123", 1400, 1440, 1390, 1439, 1420, 30000, 4300000],
                ["600519.SH", "20261124", 1425, 1463, 1420, 1457.28, 1439, 38957, 5634931.587],
            ],
        },
    }
    quote = quote_from_tushare(payload, "600519", "SH", "daily")
    assert str(quote.price) == "1457.28"
    assert quote.as_of == "20261124"
    assert quote.source == "tushare"


def test_eastmoney_board_and_search_keep_the_a_share_code():
    row = listing_from_eastmoney_row({
        "f2": 1.96, "f3": 20.25, "f4": 0.33, "f6": 76253320.68,
        "f12": "300338", "f14": "*ST开元", "f15": 1.96, "f16": 1.58, "f17": 1.6, "f18": 1.63,
    })
    assert row.market == "SZ"
    assert row.change_pct == Decimal("0.2025")
    found = listings_from_eastmoney_search([{"Code": "600519", "Name": "贵州茅台", "Classify": "AStock"}])
    assert found[0].name == "贵州茅台"
    assert found[0].market == "SH"
    suggest = listings_from_sina_suggest(
        'var suggestdata="贵州茅台,11,600519,sh600519,贵州茅台,,贵州茅台,99,1,ESG,,,";'
    )
    assert suggest[0].code == "600519"


def test_intraday_bars_keep_price_volume_and_average():
    trend = bars_from_eastmoney_trends([
        "2026-11-24 15:00,1457.24,1460.00,1460.00,1457.24,1560,227760000.00,1447.718",
    ])
    assert trend[0].open == Decimal("1457.24")
    assert trend[0].close == Decimal("1460")
    assert trend[0].high == Decimal("1460")
    assert trend[0].low == Decimal("1457.24")
    assert trend[0].volume == Decimal("1560")
    assert trend[0].avg == Decimal("1447.718")
    sina = fill_avg(bars_from_sina([
        {"day": "2026-11-24 14:59:00", "open": "1458", "high": "1460", "low": "1457", "close": "1458", "volume": "100", "amount": "145800"},
        {"day": "2026-11-24 15:00:00", "open": "1460", "high": "1462", "low": "1456", "close": "1460", "volume": "100", "amount": "146000"},
    ]))
    assert sina[0].avg == Decimal("1458")
    assert sina[1].avg == Decimal("1459")
    with pytest.raises(QuoteError, match="未知周期"):
        EastMoneyProvider().chart("600519", "tick")


def test_daily_bars_keep_ohlc_order_and_sort_by_date():
    east = bars_from_eastmoney(["2026-11-24,1425.000,1460.000,1463.260,1420.000,4292405,6000000000"])
    assert east[0].trade_date == "2026-11-24"
    assert east[0].open == Decimal("1425")
    assert east[0].close == Decimal("1460")
    assert east[0].high == Decimal("1463.26")
    assert east[0].low == Decimal("1420")
    sina = bars_from_sina([
        {"day": "2026-11-23", "open": "1475.350", "high": "1478.000", "low": "1428.000", "close": "1439.000"},
        {"day": "2026-11-24", "open": "1425.000", "high": "1463.260", "low": "1420.000", "close": "1460.000"},
    ])
    assert [bar.trade_date for bar in sina] == ["2026-11-23", "2026-11-24"]
    tushare = bars_from_tushare({
        "data": {
            "fields": ["trade_date", "open", "high", "low", "close"],
            "items": [
                ["20261124", 1425, 1463.26, 1420, 1460],
                ["20261123", 1475.35, 1478, 1428, 1439],
            ],
        }
    })
    assert [bar.trade_date for bar in tushare] == ["2026-11-23", "2026-11-24"]


def test_board_is_refused_when_the_source_has_none():
    with pytest.raises(QuoteError, match="没有涨跌榜"):
        build_router().board("sina", "gainers")


def test_quote_uses_only_the_chosen_source(monkeypatch):
    def fake(url, headers=None, timeout=8):
        if "eastmoney" in url:
            raise QuoteError("关闭")
        return SINA.encode("gb18030")

    monkeypatch.setattr("td_core.quotes.http_get", fake)
    router = QuoteRouter([EastMoneyProvider(), SinaProvider()])
    with pytest.raises(QuoteError) as caught:
        router.quote("600519", "eastmoney")
    assert caught.value.message == "关闭"
    quote = router.quote("600519", "sina")
    assert quote.source == "sina"
    with pytest.raises(QuoteError, match="请选择行情源"):
        router.quote("600519", "")
    with pytest.raises(QuoteError, match="未知行情源"):
        router.quote("600519", "other")


def test_tushare_stays_listed_until_a_token_is_set(monkeypatch):
    monkeypatch.delenv("TUSHARE_TOKEN", raising=False)
    catalog = build_router().describe()
    assert [item["id"] for item in catalog] == ["eastmoney", "sina", "tushare"]
    assert catalog[0]["ready"] is True
    assert catalog[2]["ready"] is False
    with pytest.raises(QuoteError, match="TUSHARE_TOKEN"):
        build_router().quote("600519", "tushare")
    monkeypatch.setenv("TUSHARE_TOKEN", "token")
    router = build_router()
    assert isinstance(router.providers[2], TushareProvider)
    assert router.describe()[2]["ready"] is True
