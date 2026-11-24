"""把持仓状态写成今天要执行的中文动作。"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from td_core.num import money, shares_q
from td_core.params import RuleParams, active, pct_text, ratio_text
from td_core.portfolio import EPS, PositionView
from td_core.rules import ASSET_LABELS, REGIME_LABELS

TIER_NAME = {1: "第一档", 2: "第二档", 3: "第三档"}


def _shares(value: Decimal) -> str:
    rounded = shares_q(value)
    if rounded == rounded.to_integral_value():
        return str(int(rounded))
    return format(rounded.normalize(), "f")


def _yuan(value: Decimal) -> str:
    return f"{money(value):,.2f}"


def _action(
    level: str,
    code: str,
    title: str,
    detail: str,
    plan_id: int | None = None,
    shares: Decimal | None = None,
    amount: Decimal | None = None,
) -> dict:
    return {
        "level": level,
        "code": code,
        "title": title,
        "detail": detail,
        "plan_id": plan_id,
        "shares": float(shares_q(shares)) if shares is not None else None,
        "amount": float(money(amount)) if amount is not None else None,
    }


def build_actions(
    as_of: date,
    account: dict,
    plans: list[tuple[dict, PositionView]],
    params: RuleParams | None = None,
) -> list[dict]:
    rules = active(params)
    actions: list[dict] = []
    nav: Decimal = account["nav"]
    if nav <= 0:
        actions.append(_action("warn", "nav", "先设定账户净值", "仓位比例、风险预算和回撤都按净值计算。"))
    if account.get("calendar_warning"):
        actions.append(_action("info", "calendar", "交易日历提示", account["calendar_warning"]))
    if account["cash"] < 0:
        actions.append(_action("danger", "cash", "现金为负", "这已经触及禁止融资的红线。先核对成交，再用真实现金改写账户。"))
    if account["halt_active"]:
        until = account["halt_until"].isoformat() if account["halt_until"] else f"至少 {rules.halt_days} 个交易日"
        actions.append(
            _action(
                "danger",
                "halt",
                "停止全部新交易",
                f"回撤达到 {pct_text(rules.account_dd_halt)} 或停机期尚未结束。新买入停止至 {until}，并做系统复盘。减仓不受这一条限制。",
            )
        )
    for reason in account["reasons"]:
        actions.append(
            _action(
                "warn",
                "regime",
                f"生效闸门：{REGIME_LABELS[account['effective']]}",
                reason,
            )
        )

    can_buy = nav > 0 and not account["halt_active"] and account["effective"] != "defensive"
    for meta, view in plans:
        label = f"{meta['code']} {meta['name']}"
        if meta.get("fundamental_veto") and view.shares > EPS:
            actions.append(
                _action(
                    "danger",
                    "veto",
                    f"{label}：重大否决，直接清仓",
                    "逻辑证伪、重大利空或监管风险下直接清仓，不受分级节奏限制。"
                    f"卖出后进入至少 {rules.cooling_exit_days} 个交易日冷静期。",
                    meta["id"],
                    view.sell_need,
                )
            )
        elif view.sell_need > EPS:
            tier = view.tier or 1
            sold_text = pct_text(rules.tier_fraction(tier)) if 1 <= tier <= 3 else ""
            actions.append(
                _action(
                    "danger",
                    "sell_tier",
                    f"{label}：卖出{TIER_NAME.get(tier, '风控档')}",
                    f"卖出原始持仓的 {sold_text}（本次建议 {_shares(view.sell_need)} 股）。"
                    + (
                        f"完成后进入 {rules.cooling_reduction_days} 个交易日冷静期。"
                        if tier == 1
                        else "跳空越过多档时，按实际触及的最高档一次卖完。"
                    ),
                    meta["id"],
                    view.sell_need,
                )
            )
        if view.entry_state == "cancelled":
            actions.append(
                _action(
                    "warn",
                    "cancel_entry",
                    f"{label}：取消剩余建仓",
                    f"相对 P0 下跌达到 {pct_text(1 - rules.p0_cancel)}。未完成的建仓取消，已有仓位按第一档管理，本轮不再恢复。",
                    meta["id"],
                )
            )
        elif view.entry_state == "pause_down":
            actions.append(
                _action(
                    "warn",
                    "pause_entry",
                    f"{label}：下跌 8%，暂停建仓",
                    f"收盘跌到 {ratio_text(rules.p0_pause)}×P0。重新站上 {ratio_text(rules.p0_reclaim)}×P0 且确认成交结构改善之前，不要继续买。",
                    meta["id"],
                )
            )
        elif view.entry_state == "stop_up":
            actions.append(
                _action(
                    "warn",
                    "stop_entry",
                    f"{label}：上涨达到 {pct_text(rules.p0_up - 1)}，停止剩余建仓",
                    f"价格回到 {ratio_text(rules.p0_up)}×P0 或以下，并且连续 {rules.spike_stable_days} 个交易日收盘企稳、复核通过之后，才可以恢复剩余额度。",
                    meta["id"],
                )
            )
        elif view.entry_state == "open" and view.next_buy_amount > Decimal("0.01") and can_buy:
            day_no = view.slice_index + 1
            actions.append(
                _action(
                    "plan",
                    "entry_slice",
                    f"{label}：第 {day_no} 日建仓",
                    f"计划买入 {_yuan(view.next_buy_amount)} 元。分上下午限价，避开开盘前 15 分钟和收盘前 5 分钟；偏离当日 VWAP {pct_text(rules.chase_multiple - 1)} 以上不追。",
                    meta["id"],
                    amount=view.next_buy_amount,
                )
            )
        elif view.entry_state == "open" and view.slice_in_progress and view.next_buy_amount <= Decimal("0.01"):
            actions.append(
                _action(
                    "info",
                    "entry_done_today",
                    f"{label}：今日额度已用完",
                    "不要为了完成计划在同一天加单。",
                    meta["id"],
                )
            )
        elif view.entry_state == "capped":
            actions.append(
                _action(
                    "info",
                    "entry_capped",
                    f"{label}：已到当前闸门允许的额度",
                    f"中性状态只执行计划 W 的 {pct_text(rules.neutral_executable)}；防守状态不继续建仓。未完成的额度可以放弃。",
                    meta["id"],
                )
            )
        if view.overweight_shares > EPS:
            due = view.rebalance_due.isoformat() if view.rebalance_due else ""
            late = (
                f"已经超过 {rules.rebalance_days} 个交易日。"
                if view.rebalance_overdue
                else f"须在 {rules.rebalance_days} 个交易日内完成。"
            )
            actions.append(
                _action(
                    "danger" if view.rebalance_overdue else "warn",
                    "rebalance",
                    f"{label}：权重超过{ASSET_LABELS.get(meta['asset_type'], '上限')}",
                    f"建议卖出 {_shares(view.overweight_shares)} 股，截止 {due}。{late}",
                    meta["id"],
                    view.overweight_shares,
                )
            )
        if view.cooling_active and view.cooling_until is not None:
            actions.append(
                _action(
                    "warn",
                    "cooling",
                    f"{label}：冷静期",
                    f"至 {view.cooling_until.isoformat()}（含当日）禁止买入。错过反弹也不破例。",
                    meta["id"],
                )
            )
        if view.await_close:
            actions.append(
                _action(
                    "info",
                    "await_close",
                    f"{label}：盘中未到第二档",
                    f"盘中回撤还没到第 {rules.intraday_auto_tier} 档。更浅的档等收盘确认，除非另有重大利空。",
                    meta["id"],
                )
            )
        if view.profit_band == "run_50" and view.tier == 0 and view.shares > EPS:
            actions.append(
                _action(
                    "info",
                    "run_profit",
                    f"{label}：盈利达到 {pct_text(rules.run_multiple - 1)}",
                    "基本面和趋势仍强时不机械清仓，继续按高水位回撤执行。权重超过硬上限时仍然要再平衡。",
                    meta["id"],
                )
            )

    if nav > 0:
        gross = sum((view.market_value for _, view in plans), Decimal("0"))
        if gross > nav * account["cap"] + Decimal("0.01"):
            ranked = sorted(plans, key=lambda item: (not item[0]["high_vol"], -item[1].market_value))
            names = "、".join(meta["code"] for meta, view in ranked if view.market_value > 0)[:80]
            actions.append(
                _action(
                    "danger",
                    "gross_cut",
                    "总仓超过闸门上限",
                    f"当前总仓 {_yuan(gross)}，上限是净值的 {float(account['cap']) * 100:.0f}%。优先减高相关、高波动仓位：{names}。",
                )
            )
        industry_value: dict[str, Decimal] = {}
        theme_value: dict[str, Decimal] = {}
        high_value = Decimal("0")
        for meta, view in plans:
            if view.market_value <= 0:
                continue
            if meta["industry"]:
                industry_value[meta["industry"]] = industry_value.get(meta["industry"], Decimal("0")) + view.market_value
            if meta["theme"]:
                theme_value[meta["theme"]] = theme_value.get(meta["theme"], Decimal("0")) + view.market_value
            if meta["high_vol"]:
                high_value += view.market_value
        for name, value in industry_value.items():
            if value > nav * rules.industry_cap + Decimal("0.01"):
                actions.append(
                    _action(
                        "danger",
                        "group_cap",
                        f"行业「{name}」超过 {pct_text(rules.industry_cap)}",
                        f"停止新增同主题标的，{rules.rebalance_days} 个交易日内降到上限以内。",
                    )
                )
        for name, value in theme_value.items():
            if value > nav * rules.industry_cap + Decimal("0.01"):
                actions.append(
                    _action(
                        "danger",
                        "group_cap",
                        f"主题「{name}」超过 {pct_text(rules.industry_cap)}",
                        f"停止新增同主题标的，{rules.rebalance_days} 个交易日内降到上限以内。",
                    )
                )
        if high_value > nav * rules.high_vol_group_cap + Decimal("0.01"):
            actions.append(
                _action(
                    "danger",
                    "high_vol",
                    f"高波动仓位合计超过 {pct_text(rules.high_vol_group_cap)}",
                    "停止新增，优先保留基本面和流动性更好的标的。",
                )
            )
    return actions
