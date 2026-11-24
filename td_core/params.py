"""可配置的纪律参数。V2 是手册默认值；界面另存的版本不会改写这一份。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from td_core.num import D

ASSET_TYPES = ("broad_etf", "sector_etf", "large_cap", "growth", "high_vol")
REGIME_ORDER = ("defensive", "neutral", "aggressive", "special_aggressive")


def pct_text(value: Decimal) -> str:
    shown = (value * Decimal(100)).quantize(Decimal("0.01"))
    text = format(shown, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def ratio_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def active(params: RuleParams | None) -> RuleParams:
    return params or V2


@dataclass(frozen=True)
class RuleParams:
    broad_etf_cap: Decimal = Decimal("0.25")
    sector_etf_cap: Decimal = Decimal("0.20")
    large_cap_cap: Decimal = Decimal("0.15")
    growth_cap: Decimal = Decimal("0.10")
    high_vol_name_cap: Decimal = Decimal("0.05")
    industry_cap: Decimal = Decimal("0.35")
    high_vol_group_cap: Decimal = Decimal("0.20")
    defensive_cap: Decimal = Decimal("0.40")
    neutral_cap: Decimal = Decimal("0.60")
    aggressive_cap: Decimal = Decimal("0.80")
    special_cap: Decimal = Decimal("0.90")
    neutral_executable: Decimal = Decimal("0.50")
    risk_budget_default: Decimal = Decimal("0.015")
    risk_budget_max: Decimal = Decimal("0.02")
    path_legs: tuple[tuple[Decimal, Decimal], ...] = (
        (Decimal("0.50"), Decimal("0.10")),
        (Decimal("0.25"), Decimal("0.15")),
        (Decimal("0.25"), Decimal("0.20")),
    )
    broad_etf_uses_cap_when_aggressive: bool = True
    schedules: tuple[tuple[Decimal, ...], ...] = (
        (Decimal("0.2"), Decimal("0.2"), Decimal("0.2"), Decimal("0.2"), Decimal("0.2")),
        (Decimal("0.3"), Decimal("0.3"), Decimal("0.4")),
    )
    anchor_multiple: Decimal = Decimal("1.10")
    profit_floor_multiple: Decimal = Decimal("1.30")
    run_multiple: Decimal = Decimal("1.50")
    tier_drawdowns: tuple[Decimal, Decimal, Decimal] = (Decimal("0.10"), Decimal("0.15"), Decimal("0.20"))
    tier_fractions: tuple[Decimal, Decimal, Decimal] = (Decimal("0.50"), Decimal("0.75"), Decimal("1"))
    p0_up: Decimal = Decimal("1.20")
    p0_pause: Decimal = Decimal("0.92")
    p0_cancel: Decimal = Decimal("0.90")
    p0_reclaim: Decimal = Decimal("0.95")
    chase_multiple: Decimal = Decimal("1.03")
    spike_stable_days: int = 2
    cooling_reduction_days: int = 10
    cooling_exit_days: int = 20
    special_max_days: int = 20
    account_dd_downgrade: Decimal = Decimal("0.05")
    account_dd_defensive: Decimal = Decimal("0.08")
    account_dd_halt: Decimal = Decimal("0.12")
    halt_days: int = 10
    rebalance_days: int = 5
    intraday_auto_tier: int = 2
    sell_tolerance_shares: Decimal = Decimal("1")
    sell_tolerance_pct: Decimal = Decimal("0.02")
    min_sample: int = 20
    off_rule_limit: Decimal = Decimal("0.05")

    @property
    def path_loss(self) -> Decimal:
        return sum((weight * loss for weight, loss in self.path_legs), Decimal("0"))

    def asset_caps(self) -> dict[str, Decimal]:
        return {
            "broad_etf": self.broad_etf_cap,
            "sector_etf": self.sector_etf_cap,
            "large_cap": self.large_cap_cap,
            "growth": self.growth_cap,
            "high_vol": self.high_vol_name_cap,
        }

    def asset_cap(self, asset_type: str) -> Decimal:
        return self.asset_caps()[asset_type]

    def regime_caps(self) -> dict[str, Decimal]:
        return {
            "defensive": self.defensive_cap,
            "neutral": self.neutral_cap,
            "aggressive": self.aggressive_cap,
            "special_aggressive": self.special_cap,
        }

    def regime_cap(self, regime: str) -> Decimal:
        return self.regime_caps()[regime]

    def schedule(self, days: int) -> tuple[Decimal, ...] | None:
        for weights in self.schedules:
            if len(weights) == days:
                return weights
        return None

    def entry_days(self) -> tuple[int, ...]:
        return tuple(len(weights) for weights in self.schedules)

    def tier_fraction(self, tier: int) -> Decimal:
        if tier <= 0:
            return Decimal("0")
        return self.tier_fractions[tier - 1]

    def schedule_label(self, weights: tuple[Decimal, ...]) -> str:
        days = len(weights)
        if len(set(weights)) == 1:
            return f"{days} 日，各 {pct_text(weights[0])}"
        parts = " / ".join(pct_text(weight) for weight in weights)
        return f"{days} 日，{parts}"

    def to_dict(self) -> dict:
        return {
            "asset_caps": {key: format(value, "f") for key, value in self.asset_caps().items()},
            "industry_cap": format(self.industry_cap, "f"),
            "high_vol_group_cap": format(self.high_vol_group_cap, "f"),
            "regime_caps": {key: format(value, "f") for key, value in self.regime_caps().items()},
            "neutral_executable": format(self.neutral_executable, "f"),
            "risk_budget_default": format(self.risk_budget_default, "f"),
            "risk_budget_max": format(self.risk_budget_max, "f"),
            "path_legs": [
                {"weight": format(weight, "f"), "loss": format(loss, "f")} for weight, loss in self.path_legs
            ],
            "broad_etf_uses_cap_when_aggressive": self.broad_etf_uses_cap_when_aggressive,
            "schedules": [[format(weight, "f") for weight in weights] for weights in self.schedules],
            "anchor_multiple": format(self.anchor_multiple, "f"),
            "profit_floor_multiple": format(self.profit_floor_multiple, "f"),
            "run_multiple": format(self.run_multiple, "f"),
            "tier_drawdowns": [format(value, "f") for value in self.tier_drawdowns],
            "tier_fractions": [format(value, "f") for value in self.tier_fractions],
            "p0_up": format(self.p0_up, "f"),
            "p0_pause": format(self.p0_pause, "f"),
            "p0_cancel": format(self.p0_cancel, "f"),
            "p0_reclaim": format(self.p0_reclaim, "f"),
            "chase_multiple": format(self.chase_multiple, "f"),
            "spike_stable_days": self.spike_stable_days,
            "cooling_reduction_days": self.cooling_reduction_days,
            "cooling_exit_days": self.cooling_exit_days,
            "special_max_days": self.special_max_days,
            "account_dd_downgrade": format(self.account_dd_downgrade, "f"),
            "account_dd_defensive": format(self.account_dd_defensive, "f"),
            "account_dd_halt": format(self.account_dd_halt, "f"),
            "halt_days": self.halt_days,
            "rebalance_days": self.rebalance_days,
            "intraday_auto_tier": self.intraday_auto_tier,
            "sell_tolerance_shares": format(self.sell_tolerance_shares, "f"),
            "sell_tolerance_pct": format(self.sell_tolerance_pct, "f"),
            "min_sample": self.min_sample,
            "off_rule_limit": format(self.off_rule_limit, "f"),
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> RuleParams:
        raw = data or {}
        base = V2.to_dict()
        asset = {**base["asset_caps"], **(raw.get("asset_caps") or {})}
        regime = {**base["regime_caps"], **(raw.get("regime_caps") or {})}
        legs = raw.get("path_legs") or base["path_legs"]
        schedules = raw.get("schedules") or base["schedules"]
        drawdowns = raw.get("tier_drawdowns") or base["tier_drawdowns"]
        fractions = raw.get("tier_fractions") or base["tier_fractions"]

        def pick(key: str):
            return raw[key] if key in raw and raw[key] is not None else base[key]

        return cls(
            broad_etf_cap=D(asset["broad_etf"]),
            sector_etf_cap=D(asset["sector_etf"]),
            large_cap_cap=D(asset["large_cap"]),
            growth_cap=D(asset["growth"]),
            high_vol_name_cap=D(asset["high_vol"]),
            industry_cap=D(pick("industry_cap")),
            high_vol_group_cap=D(pick("high_vol_group_cap")),
            defensive_cap=D(regime["defensive"]),
            neutral_cap=D(regime["neutral"]),
            aggressive_cap=D(regime["aggressive"]),
            special_cap=D(regime["special_aggressive"]),
            neutral_executable=D(pick("neutral_executable")),
            risk_budget_default=D(pick("risk_budget_default")),
            risk_budget_max=D(pick("risk_budget_max")),
            path_legs=tuple((D(item["weight"]), D(item["loss"])) for item in legs),
            broad_etf_uses_cap_when_aggressive=bool(pick("broad_etf_uses_cap_when_aggressive")),
            schedules=tuple(tuple(D(weight) for weight in weights) for weights in schedules),
            anchor_multiple=D(pick("anchor_multiple")),
            profit_floor_multiple=D(pick("profit_floor_multiple")),
            run_multiple=D(pick("run_multiple")),
            tier_drawdowns=tuple(D(value) for value in drawdowns),
            tier_fractions=tuple(D(value) for value in fractions),
            p0_up=D(pick("p0_up")),
            p0_pause=D(pick("p0_pause")),
            p0_cancel=D(pick("p0_cancel")),
            p0_reclaim=D(pick("p0_reclaim")),
            chase_multiple=D(pick("chase_multiple")),
            spike_stable_days=int(pick("spike_stable_days")),
            cooling_reduction_days=int(pick("cooling_reduction_days")),
            cooling_exit_days=int(pick("cooling_exit_days")),
            special_max_days=int(pick("special_max_days")),
            account_dd_downgrade=D(pick("account_dd_downgrade")),
            account_dd_defensive=D(pick("account_dd_defensive")),
            account_dd_halt=D(pick("account_dd_halt")),
            halt_days=int(pick("halt_days")),
            rebalance_days=int(pick("rebalance_days")),
            intraday_auto_tier=int(pick("intraday_auto_tier")),
            sell_tolerance_shares=D(pick("sell_tolerance_shares")),
            sell_tolerance_pct=D(pick("sell_tolerance_pct")),
            min_sample=int(pick("min_sample")),
            off_rule_limit=D(pick("off_rule_limit")),
        )

    def validate(self) -> list[str]:
        problems: list[str] = []

        def unit(name: str, value: Decimal, upper: Decimal = Decimal("1")) -> None:
            if value <= 0 or value > upper:
                problems.append(f"{name}必须大于 0 且不超过 {pct_text(upper)}")

        for label, value in (
            ("宽基上限", self.broad_etf_cap),
            ("行业 ETF 上限", self.sector_etf_cap),
            ("大型公司上限", self.large_cap_cap),
            ("成长股上限", self.growth_cap),
            ("高波动单标的上限", self.high_vol_name_cap),
            ("行业或主题合计上限", self.industry_cap),
            ("高波动合计上限", self.high_vol_group_cap),
            ("防守总仓上限", self.defensive_cap),
            ("中性总仓上限", self.neutral_cap),
            ("积极总仓上限", self.aggressive_cap),
            ("特殊积极总仓上限", self.special_cap),
            ("中性可执行比例", self.neutral_executable),
        ):
            unit(label, value)
        if not (self.defensive_cap <= self.neutral_cap <= self.aggressive_cap <= self.special_cap):
            problems.append("总仓上限需按防守、中性、积极、特殊积极递增")
        unit("常态风险预算", self.risk_budget_default)
        unit("风险预算硬顶", self.risk_budget_max)
        if self.risk_budget_default > self.risk_budget_max:
            problems.append("常态风险预算不能高于硬顶")
        if not self.path_legs:
            problems.append("风险路径至少要有一段")
        weight_sum = sum((weight for weight, _loss in self.path_legs), Decimal("0"))
        if abs(weight_sum - 1) > Decimal("0.001"):
            problems.append("风险路径的权重之和必须是 100%")
        for weight, loss in self.path_legs:
            if weight <= 0 or loss <= 0 or loss >= 1:
                problems.append("风险路径的权重和亏损幅度都必须大于 0，亏损幅度小于 100%")
        if not self.schedules:
            problems.append("至少保留一套分日建仓比例")
        seen: set[int] = set()
        for weights in self.schedules:
            if not weights or len(weights) > 20:
                problems.append("每一套建仓比例需要 1 到 20 个交易日")
                continue
            if len(weights) in seen:
                problems.append("两套建仓方案的天数不能相同")
            seen.add(len(weights))
            if any(weight <= 0 for weight in weights):
                problems.append("分日比例必须大于 0")
            if abs(sum(weights, Decimal("0")) - 1) > Decimal("0.001"):
                problems.append("每一套分日比例之和必须是 100%")
        if self.anchor_multiple <= 1:
            problems.append("切换高水位的盈利幅度必须大于 0")
        if self.profit_floor_multiple <= self.anchor_multiple:
            problems.append("保护价不低于成本的盈利幅度要高于切换高水位的幅度")
        if self.run_multiple <= self.profit_floor_multiple:
            problems.append("不机械清仓的盈利幅度要高于保护价生效的幅度")
        if len(self.tier_drawdowns) != 3 or len(self.tier_fractions) != 3:
            problems.append("卖出固定为三档")
        elif not (
            Decimal("0") < self.tier_drawdowns[0] < self.tier_drawdowns[1] < self.tier_drawdowns[2] < Decimal("1")
        ):
            problems.append("三档回撤必须递增，且都小于 100%")
        elif not (
            Decimal("0") < self.tier_fractions[0] < self.tier_fractions[1] < self.tier_fractions[2] == Decimal("1")
        ):
            problems.append("三档卖出比例必须递增，第三档卖到原始持仓的 100%")
        if self.p0_up <= 1:
            problems.append("上涨停止建仓的幅度必须大于 0")
        if not (Decimal("0") < self.p0_cancel <= self.p0_pause <= self.p0_reclaim < Decimal("1")):
            problems.append("建仓的取消线不能高于暂停线，暂停线不能高于站回线，且都要低于 P0")
        if self.chase_multiple <= 1:
            problems.append("偏离 VWAP 的追单限制必须大于 0")
        for name, value in (
            ("企稳交易日", self.spike_stable_days),
            ("减仓冷静期", self.cooling_reduction_days),
            ("清仓冷静期", self.cooling_exit_days),
            ("特殊积极期限", self.special_max_days),
            ("停机交易日", self.halt_days),
            ("再平衡期限", self.rebalance_days),
            ("最少样本", self.min_sample),
        ):
            if value < 1:
                problems.append(f"{name}至少为 1")
        if self.intraday_auto_tier not in (1, 2, 3):
            problems.append("盘中直接执行的档位只能是 1、2 或 3")
        if self.sell_tolerance_shares < 0 or self.sell_tolerance_pct < 0 or self.sell_tolerance_pct >= 1:
            problems.append("卖出容差不能为负，比例要小于 100%")
        if not (
            Decimal("0")
            < self.account_dd_downgrade
            < self.account_dd_defensive
            < self.account_dd_halt
            < Decimal("1")
        ):
            problems.append("账户回撤的下调、防守、停机三档必须递增")
        unit("规则外比例目标", self.off_rule_limit)
        return problems

    def sections(self) -> list[dict]:
        path = " + ".join(f"{pct_text(weight)}×{pct_text(loss)}" for weight, loss in self.path_legs)
        schedules = "；".join(self.schedule_label(weights) for weights in self.schedules)
        caps = self.asset_caps()
        regimes = self.regime_caps()
        return [
            {
                "title": "红线",
                "items": [
                    "不融资、不配资、不借钱放大。",
                    "不因亏损加仓，不用券商摊薄成本代替真实成本 C。",
                    "任何买入前写明失效条件。",
                    "重大否决可以一次清仓，不必走完分级节奏。",
                    "价格按前复权。分红、拆股、送转之后同步调整锚点。",
                ],
            },
            {
                "title": "锚点",
                "items": [
                    "P0 是首个建仓日全部成交的加权均价。",
                    "C 是仍持有份额的真实加权买入成本。",
                    f"H 是首次买入之后的最高日收盘，只升不降。H 未到 {ratio_text(self.anchor_multiple)}×C 时 R=C，达到后 R=H。",
                    "回撤率 = 现价 / R - 1。",
                ],
            },
            {
                "title": "市场闸门",
                "items": [
                    f"防守 {pct_text(regimes['defensive'])}，原则上不新建仓。",
                    f"中性 {pct_text(regimes['neutral'])}，只执行计划 W 的 {pct_text(self.neutral_executable)}。",
                    f"积极 {pct_text(regimes['aggressive'])}，可以按完整计划均衡建仓。",
                    f"特殊积极 {pct_text(regimes['special_aggressive'])}，必须写理由和退出条件，最长 {self.special_max_days} 个交易日。",
                    f"趋势转弱、组合回撤 {pct_text(self.account_dd_downgrade)} 或核心假设失效，立刻回到积极并降仓。",
                ],
            },
            {
                "title": "仓位",
                "items": [
                    f"单笔风险预算常态是净值的 {pct_text(self.risk_budget_default)}，最高 {pct_text(self.risk_budget_max)}。",
                    f"W_max = min(资产上限, 风险预算 / {pct_text(self.path_loss)})。路径为 {path}。",
                    f"硬上限：宽基 ETF {pct_text(caps['broad_etf'])}，行业 ETF {pct_text(caps['sector_etf'])}，大型成熟公司 {pct_text(caps['large_cap'])}，中小盘成长 {pct_text(caps['growth'])}，高波动或亏损公司 {pct_text(caps['high_vol'])}。",
                    (
                        f"积极状态下的宽基可以直接用到 {pct_text(caps['broad_etf'])}，不再按风险路径压缩。"
                        if self.broad_etf_uses_cap_when_aggressive
                        else "宽基也按风险路径和资产上限取较小值。"
                    ),
                    f"同一行业或同一主题合计不超过 {pct_text(self.industry_cap)}，高波动合计不超过 {pct_text(self.high_vol_group_cap)}。",
                ],
            },
            {
                "title": "建仓",
                "items": [
                    f"分日方案：{schedules}。按金额而不是按股数。",
                    f"相对 P0 上涨达到 {pct_text(self.p0_up - 1)} 停止剩余建仓；收盘跌 {pct_text(1 - self.p0_pause)} 暂停；跌 {pct_text(1 - self.p0_cancel)} 取消未完成部分。",
                    f"暂停后需重新站上 {ratio_text(self.p0_reclaim)}×P0。价格高于当日 VWAP {pct_text(self.chase_multiple - 1)} 以上，不追当天剩余的单。",
                    "未完成的仓位可以永久放弃。同一天不加仓多只高度相关的标的。",
                ],
            },
            {
                "title": "卖出与冷静期",
                "items": [
                    "相对 R 回撤 "
                    + " / ".join(pct_text(value) for value in self.tier_drawdowns)
                    + "，分别卖到原始持仓的 "
                    + " / ".join(pct_text(value) for value in self.tier_fractions)
                    + "。",
                    f"盘中只有到达第 {self.intraday_auto_tier} 档才立即执行，更浅的档等收盘确认。跳空越过多档时按实际到的最高档一次卖完。",
                    f"第一次减仓后 {self.cooling_reduction_days} 个交易日不能买；清仓后 {self.cooling_exit_days} 个交易日，回来时重建 P0 和 C。",
                    "冷静期内不做 T，不摊薄，不因为怕错过反弹买回。",
                ],
            },
            {
                "title": "账户",
                "items": [
                    f"自净值高点回撤 {pct_text(self.account_dd_downgrade)}，总仓上限下调一级。",
                    f"回撤 {pct_text(self.account_dd_defensive)}，进入防守，总仓降到 {pct_text(self.defensive_cap)} 以内。",
                    f"回撤 {pct_text(self.account_dd_halt)}，停止全部新交易至少 {self.halt_days} 个交易日。",
                    f"涨过资产上限的部分，{self.rebalance_days} 个交易日内再平衡。",
                    f"至少 {self.min_sample} 笔完整交易之后才看胜率、盈亏比和期望值。规则外成交目标低于 {pct_text(self.off_rule_limit)}。",
                    "改参数会另存一个版本，已经生效的版本仍可切回去。单笔成交不能改这些数。",
                ],
            },
        ]


V2 = RuleParams()
