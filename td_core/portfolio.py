"""把成交、收盘和公司行为还原成一条持仓的锚点与动作。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from td_core.calendar import add_trading_days
from td_core.num import EPS, money, px, shares_q
from td_core.params import RuleParams, active
from td_core.rules import (
    entry_slices,
    p0_lines,
    profit_band,
    regime_multiplier,
    risk_anchor,
    shares_for_tier,
    spike_recovered,
    tier_from_price,
    tier_prices,
)


@dataclass(frozen=True)
class Lot:
    trade_date: date
    price: Decimal
    shares: Decimal
    amount: Decimal
    reason: str = "entry"
    id: int = 0


@dataclass(frozen=True)
class Mark:
    trade_date: date
    price: Decimal
    kind: str
    id: int = 0


@dataclass(frozen=True)
class Corp:
    action_date: date
    price_factor: Decimal
    share_factor: Decimal


@dataclass
class PositionView:
    entry_state: str
    next_buy_amount: Decimal
    slices: list[Decimal]
    slice_index: int
    slice_in_progress: bool
    allowed_total: Decimal
    filled_amount: Decimal
    shares: Decimal = Decimal("0")
    original_shares: Decimal = Decimal("0")
    sold_shares: Decimal = Decimal("0")
    p0: Decimal | None = None
    c: Decimal | None = None
    h: Decimal | None = None
    r: Decimal | None = None
    last_price: Decimal | None = None
    last_date: date | None = None
    last_kind: str | None = None
    close_price: Decimal | None = None
    drawdown: Decimal | None = None
    tier: int = 0
    tier_prices: dict[int, Decimal] = field(default_factory=dict)
    sell_need: Decimal = Decimal("0")
    lines: dict[str, Decimal] | None = None
    lines_preview: bool = False
    cooling_kind: str | None = None
    cooling_start: date | None = None
    cooling_until: date | None = None
    cooling_active: bool = False
    breakdown: Decimal | None = None
    p0_cancelled: bool = False
    market_value: Decimal = Decimal("0")
    profit_band: str = "unknown"
    protection_floor: Decimal | None = None
    overweight_shares: Decimal = Decimal("0")
    rebalance_due: date | None = None
    rebalance_overdue: bool = False
    realized_pnl: Decimal | None = None
    flat_date: date | None = None
    unrealized_pnl: Decimal | None = None
    reentry_spent: Decimal = Decimal("0")
    await_close: bool = False
    warnings: list[str] = field(default_factory=list)


def blocks_new_plan(view: PositionView) -> bool:
    if view.shares > EPS:
        return True
    if view.original_shares <= EPS and view.entry_state not in ("abandoned", "cancelled"):
        return True
    return False


def _factor(trade_day: date, corps: list[Corp]) -> tuple[Decimal, Decimal]:
    price_factor = Decimal("1")
    share_factor = Decimal("1")
    for action in corps:
        if action.action_date > trade_day:
            price_factor *= action.price_factor
            share_factor *= action.share_factor
    return price_factor, share_factor


def _adjusted_lots(lots: list[Lot], corps: list[Corp]) -> list[tuple[Lot, Decimal, Decimal]]:
    adjusted = []
    for lot in lots:
        price_factor, share_factor = _factor(lot.trade_date, corps)
        adjusted.append((lot, lot.price * price_factor, lot.shares * share_factor))
    return adjusted


def build_position(
    *,
    buys: list[Lot],
    sells: list[Lot],
    marks: list[Mark],
    corps: list[Corp],
    as_of: date,
    w_approved: Decimal,
    entry_days: int,
    regime: str,
    nav: Decimal,
    asset_cap: Decimal,
    abandoned: bool,
    structure_ok: bool,
    up_review_ok: bool,
    fundamental_veto: bool,
    reference_price: Decimal | None,
    params: RuleParams | None = None,
) -> PositionView:
    rules = active(params)
    buys = [lot for lot in buys if lot.trade_date <= as_of]
    sells = [lot for lot in sells if lot.trade_date <= as_of]
    marks = [mark for mark in marks if mark.trade_date <= as_of]
    corps = [action for action in corps if action.action_date <= as_of]
    buys.sort(key=lambda lot: (lot.trade_date, lot.id))
    sells.sort(key=lambda lot: (lot.trade_date, lot.id))
    marks.sort(key=lambda mark: (mark.trade_date, mark.id))

    slices = entry_slices(w_approved, entry_days, rules)
    multiplier = regime_multiplier(regime, rules)
    allowed_total = money(w_approved * multiplier)
    filled_amount = money(sum((lot.amount for lot in buys), Decimal("0")))
    reentry_spent = money(sum((lot.amount for lot in buys if lot.reason == "reentry"), Decimal("0")))

    if not buys:
        state = "abandoned" if abandoned else ("blocked" if multiplier == 0 else "open")
        preview = None
        preview_flag = False
        if reference_price and reference_price > 0:
            preview = p0_lines(reference_price, rules)
            preview_flag = True
        next_amount = slices[0] if state == "open" else Decimal("0")
        next_amount = min(next_amount, allowed_total)
        return PositionView(
            entry_state=state,
            next_buy_amount=next_amount,
            slices=slices,
            slice_index=0,
            slice_in_progress=False,
            allowed_total=allowed_total,
            filled_amount=Decimal("0"),
            lines=preview,
            lines_preview=preview_flag,
            reentry_spent=reentry_spent,
        )

    adjusted_buys = _adjusted_lots(buys, corps)
    adjusted_sells = _adjusted_lots(sells, corps)
    original = sum((shares for _, _, shares in adjusted_buys), Decimal("0"))
    sold = sum((shares for _, _, shares in adjusted_sells), Decimal("0"))
    held = original - sold
    warnings: list[str] = []
    if held < -EPS:
        warnings.append("卖出股数超过买入股数，请核对公司行为因子")
        held = Decimal("0")

    first_day = buys[0].trade_date
    first_lots = [(price, shares) for lot, price, shares in adjusted_buys if lot.trade_date == first_day]
    p0 = px(sum(price * shares for price, shares in first_lots) / sum(shares for _, shares in first_lots))
    cost_num = sum((price * shares for _, price, shares in adjusted_buys), Decimal("0"))
    cost = px(cost_num / original) if original > EPS else None

    def adj_mark(mark: Mark) -> Decimal:
        price_factor, _ = _factor(mark.trade_date, corps)
        return mark.price * price_factor

    closes = [(mark, adj_mark(mark)) for mark in marks if mark.kind == "close" and mark.trade_date >= first_day]
    intras = [(mark, adj_mark(mark)) for mark in marks if mark.kind == "intraday" and mark.trade_date >= first_day]
    high = max((price for _, price in closes), default=None)
    if high is not None:
        high = px(high)
    anchor = risk_anchor(cost, high, rules) if cost is not None else None
    if anchor is not None:
        anchor = px(anchor)

    position_marks = [mark for mark in marks if mark.trade_date >= first_day]
    last_mark = position_marks[-1] if position_marks else None
    last_price = px(adj_mark(last_mark)) if last_mark else None
    close_price = px(closes[-1][1]) if closes else None
    intra_price = px(intras[-1][1]) if intras else None
    # 盘中价只在它比最后一次收盘更新时参与 15% 档。
    fresh_intra = None
    if intras and (not closes or (intras[-1][0].trade_date, intras[-1][0].id) >= (closes[-1][0].trade_date, closes[-1][0].id)):
        fresh_intra = intra_price

    levels = tier_prices(anchor, cost, high, rules) if anchor is not None and cost is not None else {}
    close_tier = tier_from_price(close_price, levels) if close_price is not None and levels else 0
    intra_tier = tier_from_price(fresh_intra, levels) if fresh_intra is not None and levels else 0
    tier = close_tier
    if intra_tier >= rules.intraday_auto_tier:
        tier = max(tier, intra_tier)
    await_close = bool(fresh_intra is not None and intra_tier == 1 and close_tier < 1)

    band_prices = [price for mark, price in closes + intras if mark.trade_date >= first_day]
    close_only = [price for _, price in closes]
    p0_cancelled = any(price <= p0 * rules.p0_cancel for price in band_prices)
    saw_pause = any(price <= p0 * rules.p0_pause for price in close_only)
    ever_spike = any(price >= p0 * rules.p0_up for price in band_prices)
    latest_close = close_only[-1] if close_only else None
    pause_still = saw_pause and not (
        structure_ok and latest_close is not None and latest_close >= p0 * rules.p0_reclaim
    )
    spike_still = ever_spike and not (spike_recovered(close_only, p0, rules) and up_review_ok)

    schedule_lots = [lot for lot in buys if lot.reason != "reentry"]
    buy_dates = sorted({lot.trade_date for lot in schedule_lots})
    if as_of in buy_dates:
        slice_index = buy_dates.index(as_of)
        in_progress = True
        already_today = sum((lot.amount for lot in schedule_lots if lot.trade_date == as_of), Decimal("0"))
    else:
        slice_index = len(buy_dates)
        in_progress = False
        already_today = Decimal("0")
    schedule_buys = filled_amount - reentry_spent
    if slice_index < len(slices):
        room = slices[slice_index] - (already_today if in_progress else Decimal("0"))
    else:
        room = Decimal("0")
    remaining_budget = allowed_total - schedule_buys
    if remaining_budget < 0:
        remaining_budget = Decimal("0")
    if room < 0:
        room = Decimal("0")

    if abandoned:
        state = "abandoned"
    elif fundamental_veto:
        state = "veto"
    elif p0_cancelled:
        state = "cancelled"
    elif pause_still:
        state = "pause_down"
    elif spike_still:
        state = "stop_up"
    elif slice_index >= len(slices) and not in_progress:
        state = "done"
    elif in_progress and slice_index == len(slices) - 1 and room <= Decimal("0.01") and remaining_budget <= Decimal("0.01"):
        state = "done"
    elif remaining_budget <= Decimal("0.01") and schedule_buys > 0 and slice_index < len(slices):
        state = "capped"
    else:
        state = "open"

    next_amount = Decimal("0")
    if state == "open":
        next_amount = min(money(room), money(remaining_budget))
        if next_amount < Decimal("0.01"):
            next_amount = Decimal("0")
            if slice_index >= len(slices) or (in_progress and room <= Decimal("0.01") and slice_index >= len(slices) - 1):
                state = "done"

    if p0_cancelled:
        tier = max(tier, 1)
    if fundamental_veto and held > EPS:
        tier = 3

    sell_need = shares_q(shares_for_tier(original, sold, tier, rules)) if tier else Decimal("0")
    if sell_need > held:
        sell_need = shares_q(held)
    if sell_need < 0:
        sell_need = Decimal("0")

    decision_price = close_price if close_price is not None else fresh_intra
    dd = None
    if decision_price is not None and anchor not in (None, 0):
        dd = decision_price / anchor - 1

    cancel_date = None
    if p0_cancelled:
        for mark, price in sorted(closes + intras, key=lambda item: (item[0].trade_date, item[0].id)):
            if price <= p0 * rules.p0_cancel:
                cancel_date = mark.trade_date
                break

    flat_date = None
    if original > EPS and held <= EPS:
        running = Decimal("0")
        for lot, _, share_count in adjusted_sells:
            running += share_count
            if running >= original - EPS:
                flat_date = lot.trade_date
                break
        if flat_date is None and sells:
            flat_date = sells[-1].trade_date

    cooling_kind = None
    cooling_start = None
    cooling_until = None
    if original > EPS and flat_date is not None:
        cooling_kind = "fundamental" if fundamental_veto else "full_exit"
        cooling_start = flat_date
        cooling_until = add_trading_days(flat_date, rules.cooling_exit_days)
    else:
        starts = []
        if sells:
            starts.append(sells[0].trade_date)
        if cancel_date is not None:
            starts.append(cancel_date)
        if starts:
            cooling_kind = "reduction"
            cooling_start = min(starts)
            cooling_until = add_trading_days(cooling_start, rules.cooling_reduction_days)
    cooling_active = cooling_until is not None and as_of <= cooling_until

    if p0_cancelled and cancel_date is not None:
        breakdown = px(p0 * rules.p0_cancel)
    elif levels:
        breakdown = levels.get(1)
    else:
        breakdown = None

    price_for_value = last_price if last_price is not None else cost
    market_value = money(held * price_for_value) if price_for_value is not None else Decimal("0")
    overweight = Decimal("0")
    rebalance_due = None
    rebalance_overdue = False
    if nav > 0 and price_for_value not in (None, 0) and market_value > nav * asset_cap + Decimal("0.01"):
        overweight = shares_q((market_value - nav * asset_cap) / price_for_value)
        first_breach = None
        for mark, price in closes:
            share_then = _shares_as_of(adjusted_buys, adjusted_sells, mark.trade_date)
            if share_then * price > nav * asset_cap + Decimal("0.01"):
                first_breach = mark.trade_date
                break
        anchor_day = first_breach or as_of
        rebalance_due = add_trading_days(anchor_day, rules.rebalance_days)
        rebalance_overdue = as_of > rebalance_due

    realized = None
    unrealized = None
    if original > EPS and held <= EPS:
        realized = money(sum((lot.amount for lot in sells), Decimal("0")) - sum((lot.amount for lot in buys), Decimal("0")))
    elif original > EPS and cost is not None:
        cost_left = filled_amount * held / original
        unrealized = money(market_value - cost_left)

    band = profit_band(cost, high, rules)
    floor = cost if band in ("floor_30", "run_50") and cost is not None else None

    return PositionView(
        entry_state=state,
        next_buy_amount=next_amount,
        slices=slices,
        slice_index=min(slice_index, max(len(slices) - 1, 0)),
        slice_in_progress=in_progress,
        allowed_total=allowed_total,
        filled_amount=filled_amount,
        shares=shares_q(held),
        original_shares=shares_q(original),
        sold_shares=shares_q(sold),
        p0=p0,
        c=cost,
        h=high,
        r=anchor,
        last_price=last_price,
        last_date=last_mark.trade_date if last_mark else None,
        last_kind=last_mark.kind if last_mark else None,
        close_price=close_price,
        drawdown=dd,
        tier=tier,
        tier_prices=levels,
        sell_need=sell_need,
        lines=p0_lines(p0, rules),
        lines_preview=False,
        cooling_kind=cooling_kind,
        cooling_start=cooling_start,
        cooling_until=cooling_until,
        cooling_active=cooling_active,
        breakdown=breakdown,
        p0_cancelled=p0_cancelled,
        market_value=market_value,
        profit_band=band,
        protection_floor=floor,
        overweight_shares=overweight,
        rebalance_due=rebalance_due,
        rebalance_overdue=rebalance_overdue,
        realized_pnl=realized,
        flat_date=flat_date,
        unrealized_pnl=unrealized,
        reentry_spent=reentry_spent,
        await_close=await_close,
        warnings=warnings,
    )


def _shares_as_of(
    buys: list[tuple[Lot, Decimal, Decimal]],
    sells: list[tuple[Lot, Decimal, Decimal]],
    day: date,
) -> Decimal:
    bought = sum((shares for lot, _, shares in buys if lot.trade_date <= day), Decimal("0"))
    sold = sum((shares for lot, _, shares in sells if lot.trade_date <= day), Decimal("0"))
    return bought - sold
