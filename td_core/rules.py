"""手册 V2.0 的纯计算。这里没有账户状态，只有公式和闸门。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from td_core.calendar import nth_trading_day_inclusive
from td_core.num import money, px
from td_core.params import REGIME_ORDER, RuleParams, active, pct_text

ASSET_CAPS: dict[str, Decimal] = active(None).asset_caps()

ASSET_LABELS = {
    "broad_etf": "宽基ETF",
    "sector_etf": "行业ETF",
    "large_cap": "大型成熟公司",
    "growth": "中小盘成长股",
    "high_vol": "高波动题材股/亏损公司",
}

REGIME_CAPS: dict[str, Decimal] = active(None).regime_caps()

REGIME_LABELS = {
    "defensive": "防守",
    "neutral": "中性",
    "aggressive": "积极",
    "special_aggressive": "特殊积极",
}

_REGIME_ORDER = list(REGIME_ORDER)

INDUSTRY_CAP = active(None).industry_cap
HIGH_VOL_CAP = active(None).high_vol_group_cap
RISK_BUDGET_MAX = active(None).risk_budget_max
RISK_BUDGET_DEFAULT = active(None).risk_budget_default

TIER_FRACTION = {
    0: Decimal("0"),
    1: active(None).tier_fractions[0],
    2: active(None).tier_fractions[1],
    3: active(None).tier_fractions[2],
}


@dataclass(frozen=True)
class Bucket:
    instrument_id: int
    market_value: Decimal
    industry: str
    theme: str
    high_vol: bool
    asset_type: str


def is_high_vol(asset_type: str, flag: bool) -> bool:
    return asset_type == "high_vol" or flag


def downgrade_regime(regime: str) -> str:
    index = _REGIME_ORDER.index(regime)
    return _REGIME_ORDER[max(0, index - 1)]


def regime_multiplier(regime: str, params: RuleParams | None = None) -> Decimal:
    rules = active(params)
    if regime == "defensive":
        return Decimal("0")
    if regime == "neutral":
        return rules.neutral_executable
    if regime in ("aggressive", "special_aggressive"):
        return Decimal("1")
    raise ValueError(f"未知市场状态：{regime}")


def w_max_amount(
    nav: Decimal,
    asset_type: str,
    risk_budget_pct: Decimal,
    regime: str,
    params: RuleParams | None = None,
) -> Decimal:
    """W_max = min(资产上限, 风险预算 / 路径亏损)。积极状态下的宽基可直接用资产上限。"""
    rules = active(params)
    cap_amount = nav * rules.asset_cap(asset_type)
    if asset_type == "broad_etf" and regime in ("aggressive", "special_aggressive") and rules.broad_etf_uses_cap_when_aggressive:
        return money(cap_amount)
    risk_amount = nav * risk_budget_pct / rules.path_loss
    return money(min(cap_amount, risk_amount))


def entry_slices(amount: Decimal, days: int, params: RuleParams | None = None) -> list[Decimal]:
    rules = active(params)
    weights = rules.schedule(days)
    if weights is None:
        allowed = "、".join(str(item) for item in rules.entry_days())
        raise ValueError(f"建仓天数不在当前规则里，可选 {allowed} 日")
    amount = money(amount)
    parts = [money(amount * weight) for weight in weights]
    parts[-1] = money(parts[-1] + (amount - sum(parts, Decimal("0"))))
    return parts


def risk_anchor(cost: Decimal, high: Decimal | None, params: RuleParams | None = None) -> Decimal:
    """H 未到设定倍数×C 时 R=C；达到后 R=H。"""
    rules = active(params)
    if high is not None and high >= cost * rules.anchor_multiple:
        return high
    return cost


def drawdown(price: Decimal, anchor: Decimal) -> Decimal:
    return price / anchor - 1


def tier_prices(
    anchor: Decimal,
    cost: Decimal,
    high: Decimal | None,
    params: RuleParams | None = None,
) -> dict[int, Decimal]:
    rules = active(params)
    levels = {
        index + 1: px(anchor * (1 - drawdown))
        for index, drawdown in enumerate(rules.tier_drawdowns)
    }
    if high is not None and high >= cost * rules.profit_floor_multiple:
        levels = {tier: max(level, px(cost)) for tier, level in levels.items()}
    return levels


def tier_from_price(price: Decimal, levels: dict[int, Decimal]) -> int:
    if price <= levels[3]:
        return 3
    if price <= levels[2]:
        return 2
    if price <= levels[1]:
        return 1
    return 0


def shares_for_tier(
    original: Decimal,
    already_sold: Decimal,
    tier: int,
    params: RuleParams | None = None,
) -> Decimal:
    target = original * active(params).tier_fraction(tier)
    need = target - already_sold
    return need if need > 0 else Decimal("0")


def p0_lines(base: Decimal, params: RuleParams | None = None) -> dict[str, Decimal]:
    rules = active(params)
    return {
        "up": px(base * rules.p0_up),
        "pause": px(base * rules.p0_pause),
        "cancel": px(base * rules.p0_cancel),
        "reclaim": px(base * rules.p0_reclaim),
    }


def chase_blocked(price: Decimal, vwap: Decimal | None, params: RuleParams | None = None) -> bool:
    """价格高于当日 VWAP 的设定幅度则不追。"""
    if vwap is None or vwap <= 0:
        return False
    return price > vwap * active(params).chase_multiple


def cooling_buy_blocked(as_of: date, cooling_until: date | None) -> bool:
    return cooling_until is not None and as_of <= cooling_until


def spike_recovered(closes: list[Decimal], base: Decimal, params: RuleParams | None = None) -> bool:
    """曾经站上上涨停止线之后，连续若干个收盘回到该线或以下。"""
    rules = active(params)
    limit = base * rules.p0_up
    last_breach = None
    for index, close in enumerate(closes):
        if close >= limit:
            last_breach = index
    if last_breach is None:
        return True
    after = closes[last_breach + 1 :]
    return len(after) >= rules.spike_stable_days and all(close <= limit for close in after)


def profit_band(cost: Decimal | None, high: Decimal | None, params: RuleParams | None = None) -> str:
    rules = active(params)
    if cost is None or high is None or cost <= 0:
        return "unknown"
    if high >= cost * rules.run_multiple:
        return "run_50"
    if high >= cost * rules.profit_floor_multiple:
        return "floor_30"
    if high >= cost * rules.anchor_multiple:
        return "protect"
    return "cost"


def assess_account(
    *,
    intent: str,
    nav: Decimal,
    peak: Decimal,
    halt_until: date | None,
    as_of: date,
    trend_weakened: bool,
    assumption_failed: bool,
    special_started: date | None,
    params: RuleParams | None = None,
) -> dict:
    rules = active(params)
    drawdown = None
    if peak > 0:
        drawdown = nav / peak - 1
    special_last = None
    special_expired = False
    if intent == "special_aggressive" and special_started is not None:
        special_last = nth_trading_day_inclusive(special_started, rules.special_max_days)
        special_expired = as_of > special_last

    aggressive_cap = pct_text(rules.aggressive_cap)
    effective = intent
    reasons: list[str] = []
    if intent == "special_aggressive" and (special_expired or trend_weakened or assumption_failed):
        effective = "aggressive"
        if special_expired:
            reasons.append(f"特殊积极状态已满 {rules.special_max_days} 个交易日，上限回到 {aggressive_cap}，需要复核")
        if trend_weakened:
            reasons.append(f"市场或行业趋势转弱，特殊积极状态取消，上限回到 {aggressive_cap}")
        if assumption_failed:
            reasons.append(f"核心假设失效，特殊积极状态取消，上限回到 {aggressive_cap}")

    if drawdown is not None and drawdown <= -rules.account_dd_halt:
        effective = "defensive"
        reasons.append(f"账户自净值高点回撤达到 {pct_text(rules.account_dd_halt)}，进入防守并停止新交易")
    elif drawdown is not None and drawdown <= -rules.account_dd_defensive:
        effective = "defensive"
        reasons.append(
            f"账户自净值高点回撤达到 {pct_text(rules.account_dd_defensive)}，进入防守状态，总仓降到 {pct_text(rules.defensive_cap)} 以内"
        )
    elif drawdown is not None and drawdown <= -rules.account_dd_downgrade:
        effective = downgrade_regime(intent)
        reasons.append(f"账户自净值高点回撤达到 {pct_text(rules.account_dd_downgrade)}，总仓上限下调一级")

    halt_active = bool(
        (drawdown is not None and drawdown <= -rules.account_dd_halt)
        or (halt_until is not None and as_of <= halt_until)
    )
    return {
        "drawdown": drawdown,
        "effective": effective,
        "cap": rules.regime_cap(effective),
        "reasons": reasons,
        "halt_active": halt_active,
        "special_last": special_last,
        "special_expired": special_expired,
    }


def field_problems(
    *,
    thesis: str,
    catalyst: str,
    risks: list[str],
    invalidation: str,
    horizon: str,
    entry_days: int,
    liquidity_ok: bool,
    params: RuleParams | None = None,
) -> list[str]:
    rules = active(params)
    problems: list[str] = []
    if len(invalidation.strip()) < 2:
        problems.append("买入前必须写明失效条件")
    if len(catalyst.strip()) < 2:
        problems.append("必须写明核心催化")
    if len(horizon.strip()) < 2:
        problems.append("必须写明投资期限")
    if len(thesis.strip()) < 2:
        problems.append("必须写明核心理由")
    filled = [item.strip() for item in risks if item and item.strip()]
    if len(filled) < 3:
        problems.append("必须写明三项主要风险")
    if rules.schedule(entry_days) is None:
        allowed = "、".join(str(item) for item in rules.entry_days())
        problems.append(f"建仓天数只能是 {allowed}")
    if not liquidity_ok:
        problems.append("必须确认流动性足以分批进出")
    return problems


def exposure_problems(
    *,
    nav: Decimal,
    regime: str,
    asset_type: str,
    industry: str,
    theme: str,
    high_vol: bool,
    instrument_id: int,
    w_approved: Decimal,
    held: list[Bucket],
    params: RuleParams | None = None,
) -> list[str]:
    rules = active(params)
    problems: list[str] = []
    if nav <= 0:
        return ["请先设置账户净值"]
    if w_approved <= 0:
        problems.append("目标仓位必须大于 0")
        return problems
    name_mv = sum((item.market_value for item in held if item.instrument_id == instrument_id), Decimal("0"))
    cap_amount = nav * rules.asset_cap(asset_type)
    if name_mv + w_approved > cap_amount + Decimal("0.01"):
        problems.append("单标的超过资产类型上限")
    industry_mv = name_mv
    theme_mv = name_mv
    high_mv = name_mv if high_vol else Decimal("0")
    gross = Decimal("0")
    for item in held:
        gross += item.market_value
        if item.instrument_id == instrument_id:
            continue
        if industry and item.industry == industry:
            industry_mv += item.market_value
        if theme and item.theme == theme:
            theme_mv += item.market_value
        if item.high_vol:
            high_mv += item.market_value
    group_limit = nav * rules.industry_cap + Decimal("0.01")
    if industry and industry_mv + w_approved > group_limit:
        problems.append(f"同一行业或主题合计超过 {pct_text(rules.industry_cap)}")
    elif theme and theme_mv + w_approved > group_limit:
        problems.append(f"同一行业或主题合计超过 {pct_text(rules.industry_cap)}")
    if high_vol and high_mv + w_approved > nav * rules.high_vol_group_cap + Decimal("0.01"):
        problems.append(f"高波动标的合计超过 {pct_text(rules.high_vol_group_cap)}")
    gross_after = gross + w_approved
    if gross_after > nav * rules.regime_cap(regime) + Decimal("0.01"):
        problems.append("总仓位超过当前闸门上限")
    if gross_after > nav + Decimal("0.01"):
        problems.append("计划仓位超过账户净值，构成融资")
    return problems


def sizing_note(asset_type: str, regime: str, params: RuleParams | None = None) -> str | None:
    rules = active(params)
    if (
        asset_type == "broad_etf"
        and regime in ("aggressive", "special_aggressive")
        and rules.broad_etf_uses_cap_when_aggressive
    ):
        return (
            f"宽基在积极状态下按资产上限 {pct_text(rules.broad_etf_cap)} 作为 W_max，"
            f"不按 {pct_text(rules.path_loss)} 风险路径压缩。"
        )
    return None


def check_risk_budget(value: Decimal, params: RuleParams | None = None) -> str | None:
    rules = active(params)
    if value <= 0 or value > rules.risk_budget_max:
        return f"单笔风险预算必须大于 0 且不超过 {pct_text(rules.risk_budget_max)}"
    return None


def correlated(industry: str, theme: str, other_industry: str, other_theme: str) -> bool:
    if industry and other_industry and industry == other_industry:
        return True
    if theme and other_theme and theme == other_theme:
        return True
    return False
