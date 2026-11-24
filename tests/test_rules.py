from datetime import date
from decimal import Decimal

from td_core.actions import build_actions
from td_core.calendar import add_trading_days, is_trading_day
from dataclasses import replace

from td_core.params import V2
from td_core.portfolio import Lot, Mark, build_position
from td_core.rules import (
    assess_account,
    chase_blocked,
    cooling_buy_blocked,
    entry_slices,
    exposure_problems,
    field_problems,
    shares_for_tier,
    tier_prices,
    w_max_amount,
    Bucket,
)
from td_core.stats import ClosedTrade, quarterly_report

DAY = date(2026, 11, 23)


def lot(day: str, price: str, shares: str, reason: str = "entry", ident: int = 1) -> Lot:
    price_d = Decimal(price)
    share_d = Decimal(shares)
    return Lot(date.fromisoformat(day), price_d, share_d, price_d * share_d, reason, ident)


def mark(day: str, price: str, kind: str = "close", ident: int = 1) -> Mark:
    return Mark(date.fromisoformat(day), Decimal(price), kind, ident)


def position(**overrides):
    base = dict(
        buys=[],
        sells=[],
        marks=[],
        corps=[],
        as_of=DAY,
        w_approved=Decimal("100000"),
        entry_days=5,
        regime="aggressive",
        nav=Decimal("1000000"),
        asset_cap=Decimal("0.15"),
        abandoned=False,
        structure_ok=False,
        up_review_ok=False,
        fundamental_veto=False,
        reference_price=None,
    )
    base.update(overrides)
    return build_position(**base)


def test_chapter12_sizing_and_lines():
    assert w_max_amount(Decimal("1000000"), "large_cap", Decimal("0.015"), "aggressive") == Decimal("109090.91")
    assert w_max_amount(Decimal("1000000"), "large_cap", Decimal("0.02"), "aggressive") == Decimal("145454.55")
    assert w_max_amount(Decimal("1000000"), "high_vol", Decimal("0.015"), "aggressive") == Decimal("50000.00")
    assert w_max_amount(Decimal("1000000"), "broad_etf", Decimal("0.015"), "aggressive") == Decimal("250000.00")
    assert entry_slices(Decimal("100000"), 5) == [Decimal("20000.00")] * 5
    assert entry_slices(Decimal("100000"), 3) == [Decimal("30000.00"), Decimal("30000.00"), Decimal("40000.00")]
    assert sum(entry_slices(Decimal("100000.01"), 5), Decimal("0")) == Decimal("100000.01")


def test_anchors_tiers_and_gap():
    levels = tier_prices(Decimal("130"), Decimal("100"), Decimal("130"))
    assert levels[1] == Decimal("117")
    assert levels[2] == Decimal("110.5")
    assert levels[3] == Decimal("104")
    built = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "130", ident=1), mark("2026-11-25", "117", ident=2)],
        as_of=date(2026, 11, 25),
    )
    assert built.p0 == Decimal("100")
    assert built.c == Decimal("100")
    assert built.h == Decimal("130")
    assert built.r == Decimal("130")
    assert built.tier == 1
    assert built.sell_need == Decimal("100")
    assert built.lines["up"] == Decimal("120")
    assert built.lines["pause"] == Decimal("92")
    assert built.lines["cancel"] == Decimal("90")
    assert built.protection_floor == Decimal("100")
    assert built.entry_state == "stop_up"
    later = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "130"), mark("2026-11-25", "120", ident=2)],
        as_of=date(2026, 11, 25),
    )
    assert later.h == Decimal("130")
    below = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "109")],
        as_of=date(2026, 11, 24),
    )
    assert below.r == Decimal("100")
    switched = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "110")],
        as_of=date(2026, 11, 24),
    )
    assert switched.r == Decimal("110")
    assert shares_for_tier(Decimal("100"), Decimal("0"), 2) == Decimal("75")
    gapped = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "130", ident=1), mark("2026-11-25", "107.9", "intraday", 2)],
        as_of=date(2026, 11, 25),
    )
    assert gapped.tier == 2
    assert gapped.sell_need == Decimal("150")
    assert gapped.p0_cancelled is False


def test_entry_pause_cancel_and_neutral_budget():
    assert position(regime="neutral").next_buy_amount == Decimal("20000.00")
    assert position(regime="neutral").allowed_total == Decimal("50000.00")
    assert position(regime="defensive").next_buy_amount == Decimal("0")
    assert position(regime="defensive").entry_state == "blocked"
    paused = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "92")],
        as_of=date(2026, 11, 24),
    )
    assert paused.entry_state == "pause_down"
    resumed = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "92"), mark("2026-11-25", "96", ident=2)],
        structure_ok=True,
        as_of=date(2026, 11, 25),
    )
    assert resumed.entry_state == "open"
    cancelled = position(
        buys=[lot("2026-11-23", "100", "200")],
        marks=[mark("2026-11-24", "90")],
        as_of=date(2026, 11, 24),
    )
    assert cancelled.entry_state == "cancelled"
    assert cancelled.sell_need == Decimal("100")
    assert cancelled.cooling_active is True
    assert cancelled.cooling_until == date(2026, 12, 8)
    spiked = position(
        buys=[lot("2026-11-23", "100", "100")],
        marks=[mark("2026-11-24", "120")],
        as_of=date(2026, 11, 24),
    )
    assert spiked.entry_state == "stop_up"
    quiet = position(
        buys=[lot("2026-11-23", "100", "100")],
        marks=[mark("2026-11-24", "119.99")],
        as_of=date(2026, 11, 24),
    )
    assert quiet.entry_state == "open"
    recovered = position(
        buys=[lot("2026-11-23", "100", "100")],
        marks=[
            mark("2026-11-24", "121", ident=1),
            mark("2026-11-25", "119", ident=2),
            mark("2026-11-26", "118", ident=3),
        ],
        up_review_ok=True,
        as_of=date(2026, 11, 26),
    )
    assert recovered.entry_state == "open"
    held = position(
        buys=[
            lot("2026-11-23", "100", "200", ident=1),
            lot("2026-11-24", "100", "200", ident=2),
            lot("2026-11-25", "100", "200", ident=3),
        ],
        regime="neutral",
        as_of=date(2026, 11, 26),
    )
    assert held.entry_state == "capped"
    assert held.next_buy_amount == Decimal("0")


def test_cooling_blocks_the_buy_window():
    built = position(
        buys=[lot("2026-11-23", "100", "200")],
        sells=[lot("2026-11-25", "117", "100", reason="tier1", ident=2)],
        marks=[mark("2026-11-24", "130"), mark("2026-11-25", "117", ident=2)],
        as_of=date(2026, 11, 26),
    )
    assert built.cooling_kind == "reduction"
    assert built.cooling_until == date(2026, 12, 9)
    assert cooling_buy_blocked(date(2026, 11, 26), built.cooling_until) is True
    assert cooling_buy_blocked(date(2026, 12, 9), built.cooling_until) is True
    assert cooling_buy_blocked(date(2026, 12, 10), built.cooling_until) is False
    actions = build_actions(
        date(2026, 11, 25),
        {
            "nav": Decimal("1000000"),
            "cash": Decimal("980000"),
            "effective": "aggressive",
            "intent": "aggressive",
            "cap": Decimal("0.8"),
            "halt_active": False,
            "halt_until": None,
            "reasons": [],
            "drawdown": Decimal("0"),
            "calendar_warning": None,
        },
        [({"id": 1, "code": "DEMO", "name": "示例股份", "industry": "消费", "theme": "龙头", "high_vol": False, "asset_type": "large_cap", "fundamental_veto": False}, position(
            buys=[lot("2026-11-23", "100", "200")],
            marks=[mark("2026-11-24", "130"), mark("2026-11-25", "117", ident=2)],
            as_of=date(2026, 11, 25),
        ))],
    )
    assert any("原始持仓的 50%" in item["detail"] for item in actions)


def test_calendar_and_chase_and_account():
    assert is_trading_day(date(2026, 11, 23))
    assert not is_trading_day(date(2026, 1, 1))
    assert not is_trading_day(date(2026, 2, 17))
    assert is_trading_day(date(2026, 2, 13))
    assert not is_trading_day(date(2026, 2, 23))
    assert is_trading_day(date(2026, 2, 24))
    assert is_trading_day(date(2026, 10, 8))
    assert add_trading_days(date(2026, 1, 30), 10) == date(2026, 2, 13)
    assert add_trading_days(date(2026, 11, 25), 10) == date(2026, 12, 9)
    assert chase_blocked(Decimal("104"), Decimal("100")) is True
    assert chase_blocked(Decimal("103"), Decimal("100")) is False
    defensive = assess_account(
        intent="aggressive",
        nav=Decimal("880000"),
        peak=Decimal("1000000"),
        halt_until=None,
        as_of=DAY,
        trend_weakened=False,
        assumption_failed=False,
        special_started=None,
    )
    assert defensive["effective"] == "defensive"
    assert defensive["halt_active"] is True
    stepped = assess_account(
        intent="special_aggressive",
        nav=Decimal("940000"),
        peak=Decimal("1000000"),
        halt_until=None,
        as_of=DAY,
        trend_weakened=False,
        assumption_failed=False,
        special_started=date(2026, 11, 2),
    )
    assert stepped["effective"] == "aggressive"
    assert stepped["halt_active"] is False


def test_exposure_fields_and_quarterly_gate():
    assert any("失效条件" in item for item in field_problems(
        thesis="理由", catalyst="催化", risks=["一", "二"], invalidation="", horizon="数月", entry_days=5, liquidity_ok=True
    ))
    held = [Bucket(1, Decimal("300000"), "消费", "龙头", False, "large_cap")]
    problems = exposure_problems(
        nav=Decimal("1000000"),
        regime="aggressive",
        asset_type="large_cap",
        industry="消费",
        theme="其他",
        high_vol=False,
        instrument_id=2,
        w_approved=Decimal("100000"),
        held=held,
    )
    assert any("35%" in item for item in problems)
    crowded = [Bucket(1, Decimal("600000"), "宽基", "指数", False, "broad_etf")]
    total = exposure_problems(
        nav=Decimal("1000000"),
        regime="aggressive",
        asset_type="broad_etf",
        industry="其他",
        theme="别的",
        high_vol=False,
        instrument_id=2,
        w_approved=Decimal("250000"),
        held=crowded,
    )
    assert any("总仓位" in item for item in total)
    trades = [
        ClosedTrade(index, "D", "名", Decimal("100") if index % 5 else Decimal("-50"), date(2026, 1, 5), None, 0)
        for index in range(1, 20)
    ]
    early = quarterly_report(trades, off_rule_fills=0, total_fills=19, nav_points=[], slippages=[])
    assert early["evaluation_ready"] is False
    assert early["stats"] is None
    trades.append(ClosedTrade(20, "D", "名", Decimal("100"), date(2026, 2, 2), None, 0))
    ready = quarterly_report(trades, off_rule_fills=0, total_fills=20, nav_points=[(DAY, Decimal("100")), (date(2026, 11, 24), Decimal("80"))], slippages=[])
    assert ready["evaluation_ready"] is True
    assert ready["stats"]["expectancy_positive"] is True
    assert ready["stats"]["max_account_drawdown"] == Decimal("-0.2")


def test_custom_drawdown_moves_the_first_tier():
    custom = replace(V2, tier_drawdowns=(Decimal("0.12"), Decimal("0.18"), Decimal("0.25")))
    levels = tier_prices(Decimal("130"), Decimal("100"), Decimal("130"), custom)
    assert levels[1] == Decimal("114.4")
    assert w_max_amount(Decimal("1000000"), "large_cap", Decimal("0.015"), "aggressive") == Decimal("109090.91")
