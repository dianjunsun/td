"""季度样本。不满 20 笔完整交易时不计算有效性结论。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from td_core.params import RuleParams, active


@dataclass(frozen=True)
class ClosedTrade:
    plan_id: int
    code: str
    name: str
    pnl: Decimal
    flat_date: date
    missed: Decimal | None
    off_rule_fills: int


def max_drawdown(points: list[tuple[date, Decimal]]) -> Decimal | None:
    if not points:
        return None
    peak: Decimal | None = None
    worst = Decimal("0")
    for _, nav in sorted(points, key=lambda item: item[0]):
        if nav <= 0:
            continue
        if peak is None or nav > peak:
            peak = nav
        if peak:
            current = nav / peak - 1
            if current < worst:
                worst = current
    return worst


def quarterly_report(
    trades: list[ClosedTrade],
    *,
    off_rule_fills: int,
    total_fills: int,
    nav_points: list[tuple[date, Decimal]],
    slippages: list[Decimal],
    params: RuleParams | None = None,
) -> dict:
    rules = active(params)
    ordered = sorted(trades, key=lambda trade: (trade.flat_date, trade.plan_id))
    ready = len(ordered) >= rules.min_sample
    closed = [
        {
            "plan_id": trade.plan_id,
            "code": trade.code,
            "name": trade.name,
            "pnl": trade.pnl,
            "flat_date": trade.flat_date,
            "missed": trade.missed,
            "off_rule_fills": trade.off_rule_fills,
        }
        for trade in ordered
    ]
    base = {
        "evaluation_ready": ready,
        "progress": len(ordered),
        "required": rules.min_sample,
        "off_rule_limit": rules.off_rule_limit,
        "closed_trades": closed,
        "off_rule_count": off_rule_fills,
        "fill_count": total_fills,
        "reminder": (
            f"样本不足 {rules.min_sample} 笔完整交易，只记录进度，不给策略结论。"
            if not ready
            else (
                f"样本已满 {rules.min_sample} 笔。下面只描述结果。要改阈值，在规则页另存一个版本。"
                "连续两个季度期望值为负时，先区分选股、闸门、仓位和执行，再统一修订。"
            )
        ),
        "stats": None,
    }
    if not ready:
        return base

    wins = [trade.pnl for trade in ordered if trade.pnl > 0]
    losses = [trade.pnl for trade in ordered if trade.pnl < 0]
    win_rate = Decimal(len(wins)) / Decimal(len(ordered))
    avg_win = sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else Decimal("0")
    avg_loss = abs(sum(losses, Decimal("0")) / Decimal(len(losses))) if losses else Decimal("0")
    payoff = (avg_win / avg_loss) if avg_loss > 0 else None
    expectancy = win_rate * avg_win - (1 - win_rate) * avg_loss
    streak = 0
    worst_streak = 0
    for trade in ordered:
        if trade.pnl < 0:
            streak += 1
            worst_streak = max(worst_streak, streak)
        else:
            streak = 0
    known_missed = [trade.missed for trade in ordered if trade.missed is not None]
    ratio = Decimal(off_rule_fills) / Decimal(total_fills) if total_fills else Decimal("0")
    base["stats"] = {
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff": payoff,
        "expectancy": expectancy,
        "max_consecutive_losses": worst_streak,
        "max_account_drawdown": max_drawdown(nav_points),
        "missed_rebound": sum(known_missed, Decimal("0")) if known_missed else None,
        "missed_coverage": f"{len(known_missed)}/{len(ordered)}",
        "avg_slippage": (sum(slippages, Decimal("0")) / Decimal(len(slippages))) if slippages else None,
        "off_rule_ratio": ratio,
        "expectancy_positive": expectancy > 0,
        "off_rule_below_5pct": ratio < rules.off_rule_limit,
    }
    return base
