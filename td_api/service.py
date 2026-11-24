"""把手册规则应用到 SQLite 里的账户和成交。"""

from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from td_core.actions import build_actions
from td_core.calendar import add_trading_days, calendar_warning, is_trading_day
from td_core.handbook import HANDBOOK
from td_core.num import money, store_decimal
from td_core.params import RuleParams, pct_text, ratio_text
from td_core.portfolio import Corp, Lot, Mark, PositionView, blocks_new_plan, build_position
from td_core.rules import (
    ASSET_CAPS,
    ASSET_LABELS,
    REGIME_CAPS,
    REGIME_LABELS,
    Bucket,
    assess_account,
    chase_blocked,
    check_risk_budget,
    cooling_buy_blocked,
    correlated,
    entry_slices,
    exposure_problems,
    field_problems,
    is_high_vol,
    p0_lines,
    regime_multiplier,
    sizing_note,
    tier_prices,
    w_max_amount,
)
from td_core.stats import ClosedTrade, quarterly_report
from td_api.db import Database

ENTRY_LABELS = {
    "open": "可建仓",
    "blocked": "闸门不允许",
    "pause_down": "下跌暂停",
    "stop_up": "上涨暂停",
    "cancelled": "建仓已取消",
    "abandoned": "已放弃剩余额度",
    "done": "计划额度已完成",
    "capped": "已到闸门额度",
    "veto": "重大否决",
}

def band_label(band: str, params: RuleParams) -> str:
    if band == "cost":
        return f"未盈利 {pct_text(params.anchor_multiple - 1)}，按成本控制"
    if band == "protect":
        return "已切换到高水位"
    if band == "floor_30":
        return f"盈利达到 {pct_text(params.profit_floor_multiple - 1)}，保护价不低于成本"
    if band == "run_50":
        return f"盈利达到 {pct_text(params.run_multiple - 1)}，不机械清仓"
    return "尚未形成高水位"


def buy_state_message(state: str, params: RuleParams) -> str:
    if state == "cancelled":
        return f"相对 P0 下跌达到 {pct_text(1 - params.p0_cancel)}，本轮建仓已取消"
    if state == "pause_down":
        return f"建仓已暂停，需重新站上 {ratio_text(params.p0_reclaim)}×P0 并确认成交结构改善"
    if state == "stop_up":
        return f"相对 P0 上涨达到 {pct_text(params.p0_up - 1)}，停止剩余建仓"
    return BUY_STATE_BLOCK.get(state, "当前不能买入")

BUY_STATE_BLOCK = {
    "abandoned": "剩余建仓已放弃",
    "veto": "已登记重大否决，禁止买入",
    "cancelled": "相对 P0 下跌达到 10%，本轮建仓已取消",
    "pause_down": "建仓已暂停，需重新站上 0.95×P0 并确认成交结构改善",
    "stop_up": "相对 P0 上涨达到 20%，停止剩余建仓",
    "blocked": "防守状态原则上禁止新建仓",
    "capped": "已达到当前闸门允许的建仓额度",
    "done": "计划额度已经建完",
}


class ServiceError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def today_sh() -> date:
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def parse_day(value: str | None, fallback: date | None = None) -> date:
    if not value:
        return fallback or today_sh()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ServiceError("日期格式应为 YYYY-MM-DD") from exc


def dec(value: object, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    return Decimal(str(value))


def num(value: Decimal | None, places: str = "0.0001") -> float | None:
    if value is None:
        return None
    quantized = Decimal(value).quantize(Decimal(places), rounding=ROUND_HALF_UP)
    return float(quantized)


def iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _json_numbers(value):
    if isinstance(value, str):
        try:
            number = Decimal(value)
        except Exception:
            return value
        return float(number)
    if isinstance(value, list):
        return [_json_numbers(item) for item in value]
    if isinstance(value, dict):
        return {key: _json_numbers(item) for key, item in value.items()}
    return value


def require_trading_day(day: date) -> None:
    if not is_trading_day(day):
        raise ServiceError("该日不是沪深交易日")


class Service:
    def __init__(self, db: Database):
        self.db = db

    def snapshot(self, as_of: date | None = None) -> dict:
        day = as_of or today_sh()
        with self.db.session() as conn:
            bundle = self._bundle(conn, day)
            weekly = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM weekly_reviews ORDER BY week_ending DESC, id DESC LIMIT 12"
                )
            ]
            notes = [dict(row) for row in conn.execute("SELECT * FROM rule_notes ORDER BY id")]
            nav_points = [
                (date.fromisoformat(row["as_of"]), dec(row["nav"]))
                for row in conn.execute("SELECT as_of, nav FROM nav_snapshots WHERE as_of <= ? ORDER BY as_of, id", (day.isoformat(),))
            ]
        return self._public_snapshot(day, bundle, weekly, notes, nav_points)

    def update_account(self, data: dict) -> dict:
        day = parse_day(data.get("as_of"))
        nav = money(dec(data.get("nav")))
        cash = money(dec(data.get("cash")))
        regime = data.get("regime_intent") or "neutral"
        if regime not in REGIME_CAPS:
            raise ServiceError("未知市场状态")
        with self.db.session() as conn:
            params = self._active_params(conn)
        budget = dec(data.get("risk_budget_pct", store_decimal(params.risk_budget_default)))
        budget_error = check_risk_budget(budget, params)
        if budget_error:
            raise ServiceError(budget_error)
        if nav < 0:
            raise ServiceError("净值不能为负")
        evidence = (data.get("regime_evidence") or "").strip()
        special_reason = (data.get("special_reason") or "").strip()
        special_exit = (data.get("special_exit") or "").strip()
        if regime == "special_aggressive" and (len(special_reason) < 2 or len(special_exit) < 2):
            raise ServiceError("特殊积极状态必须写明理由和退出条件")
        with self.db.session() as conn:
            current = dict(conn.execute("SELECT * FROM account WHERE id = 1").fetchone())
            peak = dec(current["nav_peak"])
            peak_date = current["peak_date"]
            if nav >= peak:
                peak = nav
                peak_date = day.isoformat()
            drawdown = (nav / peak - 1) if peak > 0 else None
            halt = current["halt_new_until"]
            if drawdown is not None and drawdown <= -params.account_dd_halt:
                proposed = add_trading_days(day, params.halt_days).isoformat()
                if halt is None or day > date.fromisoformat(halt):
                    halt = proposed
            started = current["special_started_on"]
            if regime == "special_aggressive" and (current["regime_intent"] != "special_aggressive" or not started):
                started = day.isoformat()
            conn.execute(
                """
                UPDATE account SET nav=?, cash=?, nav_peak=?, peak_date=?, regime_intent=?,
                  regime_evidence=?, special_reason=?, special_exit=?, special_started_on=?,
                  trend_weakened=?, assumption_failed=?, risk_budget_pct=?, halt_new_until=?
                WHERE id = 1
                """,
                (
                    store_decimal(nav),
                    store_decimal(cash),
                    store_decimal(peak),
                    peak_date,
                    regime,
                    evidence,
                    special_reason,
                    special_exit,
                    started,
                    1 if data.get("trend_weakened") else 0,
                    1 if data.get("assumption_failed") else 0,
                    store_decimal(budget),
                    halt,
                ),
            )
            conn.execute(
                """
                INSERT INTO nav_snapshots (as_of, nav, cash, nav_peak, drawdown, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    day.isoformat(),
                    store_decimal(nav),
                    store_decimal(cash),
                    store_decimal(peak),
                    store_decimal(drawdown) if drawdown is not None else None,
                    now_iso(),
                ),
            )
        return self.snapshot(day)

    def create_instrument(self, data: dict) -> dict:
        code = (data.get("code") or "").strip()
        name = (data.get("name") or "").strip()
        asset = data.get("asset_type") or ""
        industry = (data.get("industry") or "").strip()
        theme = (data.get("theme") or "").strip()
        if not code or not name:
            raise ServiceError("代码和名称都不能空")
        if asset not in ASSET_CAPS:
            raise ServiceError("未知资产类型")
        if not industry and not theme:
            raise ServiceError("必须填写行业或主题")
        high = 1 if is_high_vol(asset, bool(data.get("high_vol"))) else 0
        with self.db.session() as conn:
            try:
                cursor = conn.execute(
                    """
                    INSERT INTO instruments (code, name, asset_type, industry, theme, high_vol, liquidity_note)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (code, name, asset, industry, theme, high, (data.get("liquidity_note") or "").strip()),
                )
            except Exception as exc:
                if "UNIQUE" in str(exc).upper():
                    raise ServiceError("代码已存在") from exc
                raise
            return {"id": cursor.lastrowid}

    def list_watch(self) -> list[dict]:
        with self.db.session() as conn:
            rows = conn.execute("SELECT code, name, market FROM watchlist ORDER BY created_at, code")
            return [dict(row) for row in rows]

    def add_watch(self, data: dict) -> list[dict]:
        code = (data.get("code") or "").strip()
        name = (data.get("name") or "").strip() or code
        market = (data.get("market") or "").strip()
        if not code:
            raise ServiceError("代码不能空")
        with self.db.session() as conn:
            existing = conn.execute("SELECT code FROM watchlist WHERE code = ?", (code,)).fetchone()
            count = conn.execute("SELECT COUNT(*) AS n FROM watchlist").fetchone()["n"]
            if existing is None and count >= 30:
                raise ServiceError("自选最多 30 只")
            conn.execute(
                """
                INSERT INTO watchlist (code, name, market, created_at) VALUES (?, ?, ?, ?)
                ON CONFLICT(code) DO UPDATE SET name = excluded.name, market = excluded.market
                """,
                (code, name, market, now_iso()),
            )
        return self.list_watch()

    def remove_watch(self, code: str) -> list[dict]:
        with self.db.session() as conn:
            conn.execute("DELETE FROM watchlist WHERE code = ?", (code.strip(),))
        return self.list_watch()

    def preview_plan(self, data: dict) -> dict:
        day = parse_day(data.get("as_of"))
        with self.db.session() as conn:
            problems, info = self._plan_computation(conn, data, day)
        if info.get("instrument") is None:
            return {
                "w_max": None,
                "cap_amount": None,
                "risk_amount": None,
                "executable_now": None,
                "multiplier": None,
                "slices": [],
                "entry_lines": None,
                "tier_preview": [],
                "notes": [],
                "errors": problems,
            }
        return {
            "w_max": info["w_max_amount"],
            "cap_amount": info["cap_amount"],
            "risk_amount": info["risk_amount"],
            "executable_now": info["executable_now"],
            "multiplier": info["multiplier"],
            "slices": info["slices"],
            "entry_lines": info["entry_lines"],
            "tier_preview": info["tier_preview"],
            "notes": info["notes"],
            "errors": problems,
        }

    def create_plan(self, data: dict) -> dict:
        day = parse_day(data.get("as_of"))
        with self.db.session() as conn:
            problems, info = self._plan_computation(conn, data, day)
            if problems:
                raise ServiceError("；".join(problems))
            instrument = info["instrument"]
            prior = info["prior"]
            if prior is not None:
                self._reentry_gate(data, prior, info["market_price"])
            cursor = conn.execute(
                """
                INSERT INTO plans (
                  instrument_id, thesis, catalyst, risks_json, invalidation, horizon,
                  regime_snapshot, w_approved, w_max, entry_days, reference_price,
                  liquidity_ok, industry_ok, fundamental_ok, new_fact, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    instrument["id"],
                    data.get("thesis", "").strip(),
                    data.get("catalyst", "").strip(),
                    json.dumps([item.strip() for item in data.get("risks") or []], ensure_ascii=False),
                    data.get("invalidation", "").strip(),
                    data.get("horizon", "").strip(),
                    info["regime"],
                    store_decimal(info["w_approved"]),
                    store_decimal(info["w_max"]),
                    info["entry_days"],
                    store_decimal(info["reference"]) if info["reference"] is not None else None,
                    1,
                    1 if data.get("industry_ok") else 0,
                    1 if data.get("fundamental_ok") else 0,
                    (data.get("new_fact") or "").strip(),
                    now_iso(),
                ),
            )
            return {"id": cursor.lastrowid}

    def add_fill(self, plan_id: int, data: dict) -> dict:
        day = parse_day(data.get("trade_date"))
        require_trading_day(day)
        side = data.get("side")
        if side not in ("buy", "sell"):
            raise ServiceError("方向只能是买入或卖出")
        price = dec(data.get("price"))
        shares = dec(data.get("shares"))
        if price <= 0 or shares <= 0:
            raise ServiceError("价格和股数必须大于 0")
        amount = money(price * shares)
        vwap = dec(data["vwap"]) if data.get("vwap") not in (None, "") else None
        slippage = dec(data["slippage"]) if data.get("slippage") not in (None, "") else None
        breach = bool(data.get("record_breach"))
        reason = data.get("reason") or ("entry" if side == "buy" else "manual")
        note = (data.get("note") or "").strip()
        breach_reason = (data.get("off_rule_reason") or "").strip()
        session = data.get("session") or "am"
        if session not in ("am", "pm", "close", "intraday"):
            raise ServiceError("时段只能是上午、下午、收盘或盘中")
        if breach and len(breach_reason) < 2:
            raise ServiceError("规则外成交必须写明原因")
        with self.db.session() as conn:
            bundle = self._bundle(conn, day)
            found = self._find(bundle, plan_id)
            plan, instrument, view = found
            if side == "buy":
                self._guard_buy(bundle, plan, instrument, view, day, price, amount, vwap, reason, breach)
            else:
                self._guard_sell(view, plan, shares, reason, breach, bundle["params"])
            cash = dec(bundle["account"]["cash"])
            if side == "buy" and amount > cash + Decimal("0.01") and not breach:
                raise ServiceError("现金不足，禁止融资")
            cash = money(cash - amount if side == "buy" else cash + amount)
            cursor = conn.execute(
                """
                INSERT INTO fills (
                  plan_id, side, trade_date, session, price, shares, amount, vwap, reason,
                  slippage, off_rule, off_rule_reason, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    plan_id,
                    side,
                    day.isoformat(),
                    session,
                    store_decimal(price),
                    store_decimal(shares),
                    store_decimal(amount),
                    store_decimal(vwap) if vwap is not None else None,
                    reason,
                    store_decimal(slippage) if slippage is not None else None,
                    1 if breach else 0,
                    breach_reason,
                    note,
                    now_iso(),
                ),
            )
            conn.execute("UPDATE account SET cash = ? WHERE id = 1", (store_decimal(cash),))
            return {"id": cursor.lastrowid}

    def add_mark(self, plan_id: int, data: dict) -> dict:
        day = parse_day(data.get("trade_date"))
        require_trading_day(day)
        price = dec(data.get("price"))
        if price <= 0:
            raise ServiceError("价格必须大于 0")
        kind = data.get("kind") or "close"
        if kind not in ("close", "intraday"):
            raise ServiceError("价格类型只能是收盘或盘中")
        source = (data.get("source") or "").strip()
        if len(source) < 1:
            raise ServiceError("必须注明价格来源和时点")
        with self.db.session() as conn:
            self._plan_row(conn, plan_id)
            cursor = conn.execute(
                """
                INSERT INTO marks (plan_id, trade_date, price, source, kind, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (plan_id, day.isoformat(), store_decimal(price), source, kind, (data.get("note") or "").strip(), now_iso()),
            )
            return {"id": cursor.lastrowid}

    def set_flags(self, plan_id: int, data: dict) -> dict:
        fields = []
        values: list[object] = []
        for key in ("structure_ok", "up_review_ok", "industry_ok", "fundamental_ok"):
            if key in data:
                fields.append(f"{key} = ?")
                values.append(1 if data[key] else 0)
        if not fields:
            raise ServiceError("没有要更新的复核项")
        values.append(plan_id)
        with self.db.session() as conn:
            self._plan_row(conn, plan_id)
            conn.execute(f"UPDATE plans SET {', '.join(fields)} WHERE id = ?", values)
        return {"ok": True}

    def abandon(self, plan_id: int) -> dict:
        with self.db.session() as conn:
            self._plan_row(conn, plan_id)
            conn.execute("UPDATE plans SET abandoned = 1 WHERE id = ?", (plan_id,))
        return {"ok": True}

    def veto(self, plan_id: int, data: dict) -> dict:
        note = (data.get("note") or "").strip()
        if len(note) < 2:
            raise ServiceError("重大否决要写明事实")
        with self.db.session() as conn:
            self._plan_row(conn, plan_id)
            conn.execute(
                "UPDATE plans SET fundamental_veto = 1, veto_note = ? WHERE id = ?",
                (note, plan_id),
            )
        return {"ok": True}

    def approve_reentry(self, plan_id: int, data: dict) -> dict:
        day = parse_day(data.get("as_of"))
        amount = money(dec(data.get("w_approved")))
        if amount <= 0:
            raise ServiceError("重新准入的金额必须大于 0")
        if not data.get("industry_ok") or not data.get("fundamental_ok"):
            raise ServiceError("重新准入需要确认行业没有继续恶化，并且基本面复核通过")
        with self.db.session() as conn:
            bundle = self._bundle(conn, day)
            plan, instrument, view = self._find(bundle, plan_id)
            if plan["fundamental_veto"] or view.p0_cancelled:
                raise ServiceError("P0 取消或重大否决之后，不能在原计划里买回")
            if view.cooling_until is None or cooling_buy_blocked(day, view.cooling_until):
                raise ServiceError("冷静期尚未结束")
            if bundle["assessed"]["halt_active"] or bundle["assessed"]["effective"] == "defensive":
                raise ServiceError("当前闸门不允许重新买入")
            if view.tier >= 1 or (view.breakdown and (view.last_price is None or view.last_price < view.breakdown)):
                raise ServiceError("价格尚未重新站上前次破位位")
            problems = exposure_problems(
                nav=dec(bundle["account"]["nav"]),
                regime=bundle["assessed"]["effective"],
                asset_type=instrument["asset_type"],
                industry=instrument["industry"],
                theme=instrument["theme"],
                high_vol=is_high_vol(instrument["asset_type"], bool(instrument["high_vol"])),
                instrument_id=instrument["id"],
                w_approved=amount,
                held=self._buckets(bundle),
            )
            if problems:
                raise ServiceError("；".join(problems))
            conn.execute(
                "UPDATE plans SET reentry_w = ?, industry_ok = 1, fundamental_ok = 1 WHERE id = ?",
                (store_decimal(amount), plan_id),
            )
        return {"ok": True}

    def set_missed(self, plan_id: int, data: dict) -> dict:
        if data.get("missed_rebound") in (None, ""):
            raise ServiceError("要填写错失收益")
        missed = dec(data.get("missed_rebound"))
        with self.db.session() as conn:
            self._plan_row(conn, plan_id)
            conn.execute(
                "UPDATE plans SET missed_rebound = ? WHERE id = ?",
                (store_decimal(missed), plan_id),
            )
        return {"ok": True}

    def add_corporate_action(self, data: dict) -> dict:
        kind = data.get("kind") or ""
        if kind not in ("dividend", "split", "reverse_split", "rights", "bonus"):
            raise ServiceError("未知公司行为")
        price_factor = dec(data.get("price_factor"))
        share_factor = dec(data.get("share_factor"))
        if price_factor <= 0 or share_factor <= 0:
            raise ServiceError("复权因子必须大于 0")
        day = parse_day(data.get("action_date"))
        with self.db.session() as conn:
            instrument = conn.execute("SELECT id FROM instruments WHERE id = ?", (data.get("instrument_id"),)).fetchone()
            if instrument is None:
                raise ServiceError("找不到标的")
            cursor = conn.execute(
                """
                INSERT INTO corporate_actions (instrument_id, action_date, kind, price_factor, share_factor, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["instrument_id"],
                    day.isoformat(),
                    kind,
                    store_decimal(price_factor),
                    store_decimal(share_factor),
                    (data.get("note") or "").strip(),
                    now_iso(),
                ),
            )
            return {"id": cursor.lastrowid}

    def add_weekly(self, data: dict) -> dict:
        day = parse_day(data.get("week_ending"))
        decision = (data.get("decision") or "").strip()
        if len(decision) < 2:
            raise ServiceError("周度决策不能空")
        with self.db.session() as conn:
            bundle = self._bundle(conn, day)
            cursor = conn.execute(
                """
                INSERT INTO weekly_reviews (week_ending, regime, exposure_note, correlation_note, decision, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    day.isoformat(),
                    bundle["assessed"]["effective"],
                    (data.get("exposure_note") or "").strip(),
                    (data.get("correlation_note") or "").strip(),
                    decision,
                    now_iso(),
                ),
            )
            return {"id": cursor.lastrowid}

    def add_rule_note(self, data: dict) -> dict:
        note = (data.get("note") or "").strip()
        if len(note) < 2:
            raise ServiceError("纪要不能空")
        with self.db.session() as conn:
            cursor = conn.execute(
                "INSERT INTO rule_notes (version, note, created_at) VALUES (?, ?, ?)",
                (self._active_rule_row(conn)["name"], note, now_iso()),
            )
            return {"id": cursor.lastrowid}

    def handbook(self) -> dict:
        with self.db.session() as conn:
            row = self._active_rule_row(conn)
            params = RuleParams.from_dict(json.loads(row["params_json"]))
        return {
            "version": row["name"],
            "effective_on": row["created_at"][:10],
            "priority": HANDBOOK["priority"],
            "disclaimer": HANDBOOK["disclaimer"],
            "sections": params.sections(),
        }

    def rule_catalog(self) -> dict:
        with self.db.session() as conn:
            rows = [dict(row) for row in conn.execute("SELECT * FROM rule_versions ORDER BY id")]
        versions = [self._version_public(row) for row in rows]
        return {"versions": versions, "active_id": next(item["id"] for item in versions if item["active"])}

    def save_rule_version(self, data: dict) -> dict:
        name = (data.get("name") or "").strip()
        if not name:
            raise ServiceError("请给这一版规则起个名字")
        note = (data.get("note") or "").strip()
        try:
            params = RuleParams.from_dict(data.get("params") or {})
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ServiceError("规则参数无法读取") from exc
        problems = params.validate()
        if problems:
            raise ServiceError("；".join(problems))
        with self.db.session() as conn:
            conn.execute("UPDATE rule_versions SET active = 0")
            cursor = conn.execute(
                """
                INSERT INTO rule_versions (name, note, params_json, active, created_at)
                VALUES (?, ?, ?, 1, ?)
                """,
                (name, note, json.dumps(params.to_dict(), ensure_ascii=False), now_iso()),
            )
            row = dict(conn.execute("SELECT * FROM rule_versions WHERE id = ?", (cursor.lastrowid,)).fetchone())
        return self._version_public(row)

    def activate_rule_version(self, version_id: int) -> dict:
        with self.db.session() as conn:
            row = conn.execute("SELECT * FROM rule_versions WHERE id = ?", (version_id,)).fetchone()
            if row is None:
                raise ServiceError("找不到这一版规则")
            row = dict(row)
            RuleParams.from_dict(json.loads(row["params_json"]))
            conn.execute("UPDATE rule_versions SET active = 0")
            conn.execute("UPDATE rule_versions SET active = 1 WHERE id = ?", (version_id,))
            row["active"] = 1
        return self._version_public(row)

    def _version_public(self, row: dict) -> dict:
        params = RuleParams.from_dict(json.loads(row["params_json"]))
        public = self._public_rule(row, params)
        public["sections"] = params.sections()
        return public

    def _public_rule(self, row: dict, params: RuleParams) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "note": row["note"],
            "created_at": row["created_at"],
            "active": bool(row["active"]),
            "params": _json_numbers(params.to_dict()),
            "schedules": [
                {"days": len(weights), "label": params.schedule_label(weights)} for weights in params.schedules
            ],
            "path_loss": float(params.path_loss),
            "risk_budget_default": float(params.risk_budget_default),
            "risk_budget_max": float(params.risk_budget_max),
            "cooling_reduction_days": params.cooling_reduction_days,
            "cooling_exit_days": params.cooling_exit_days,
            "off_rule_limit": float(params.off_rule_limit),
            "p0_cancel": float(params.p0_cancel),
        }

    def _plan_computation(self, conn, data: dict, day: date) -> tuple[list[str], dict]:
        bundle = self._bundle(conn, day)
        params = bundle["params"]
        account = bundle["account"]
        assessed = bundle["assessed"]
        nav = dec(account["nav"])
        regime = assessed["effective"]
        problems: list[str] = []
        instrument = conn.execute("SELECT * FROM instruments WHERE id = ?", (data.get("instrument_id"),)).fetchone()
        if instrument is None:
            return ["找不到标的"], {"instrument": None}
        instrument = dict(instrument)
        w_value = data.get("w_approved")
        w_approved = money(dec(w_value)) if w_value not in (None, "") else Decimal("0")
        entry_days = int(data.get("entry_days") or 0)
        reference = dec(data["reference_price"]) if data.get("reference_price") not in (None, "") else None
        budget = dec(account["risk_budget_pct"])
        w_max = w_max_amount(nav, instrument["asset_type"], budget, regime, params) if nav > 0 else Decimal("0")
        cap_amount = money(nav * params.asset_cap(instrument["asset_type"])) if nav > 0 else Decimal("0")
        risk_amount = money(nav * budget / params.path_loss) if nav > 0 and params.path_loss > 0 else Decimal("0")
        try:
            slices = entry_slices(w_approved, entry_days, params) if w_approved > 0 and params.schedule(entry_days) else []
        except ValueError as exc:
            slices = []
            problems.append(str(exc))
        problems.extend(
            field_problems(
                thesis=data.get("thesis") or "",
                catalyst=data.get("catalyst") or "",
                risks=list(data.get("risks") or []),
                invalidation=data.get("invalidation") or "",
                horizon=data.get("horizon") or "",
                entry_days=entry_days,
                liquidity_ok=bool(data.get("liquidity_ok")),
                params=params,
            )
        )
        if assessed["halt_active"]:
            problems.append("新交易已停止")
        if regime == "defensive":
            problems.append("防守状态原则上禁止新建仓")
        if nav > 0 and w_approved > w_max + Decimal("0.01"):
            problems.append(f"批准仓位超过风险预算允许的 W_max（{w_max}）")
        if regime != "defensive":
            problems.extend(
                exposure_problems(
                    nav=nav,
                    regime=regime,
                    asset_type=instrument["asset_type"],
                    industry=instrument["industry"],
                    theme=instrument["theme"],
                    high_vol=is_high_vol(instrument["asset_type"], bool(instrument["high_vol"])),
                    instrument_id=instrument["id"],
                    w_approved=w_approved,
                    held=self._buckets(bundle),
                    params=params,
                )
            )
        prior = None
        for plan, inst, view in bundle["built"]:
            if inst["id"] != instrument["id"]:
                continue
            if blocks_new_plan(view):
                problems.append("该标的已有未完成计划或仍有持仓")
            if view.cooling_active:
                problems.append("冷静期内禁止买入")
            if view.original_shares > 0 and (prior is None or plan["id"] > prior[0]["id"]):
                prior = (plan, view)
        notes = []
        special = sizing_note(instrument["asset_type"], regime, params)
        if special:
            notes.append(special)
        if regime == "neutral":
            notes.append(f"中性状态只执行计划 W 的 {pct_text(params.neutral_executable)}。")
        lines = None
        tier_preview = []
        fractions = params.tier_fractions
        if reference and reference > 0:
            lines = {key: num(value, "0.0001") for key, value in p0_lines(reference, params).items()}
            levels = tier_prices(reference, reference, None, params)
            for tier, fraction in enumerate(fractions, start=1):
                tier_preview.append(
                    {
                        "tier": tier,
                        "sell_fraction": float(fraction),
                        "price": num(levels[tier], "0.0001"),
                    }
                )
        else:
            for tier, fraction in enumerate(fractions, start=1):
                tier_preview.append({"tier": tier, "sell_fraction": float(fraction), "price": None})
        multiplier = regime_multiplier(regime, params) if regime in REGIME_CAPS else Decimal("0")
        info = {
            "instrument": instrument,
            "regime": regime,
            "w_approved": w_approved,
            "w_max": w_max,
            "entry_days": entry_days,
            "reference": reference,
            "prior": prior[1] if prior else None,
            "market_price": dec(data["market_price"]) if data.get("market_price") not in (None, "") else None,
            "w_max_amount": num(w_max, "0.01"),
            "cap_amount": num(cap_amount, "0.01"),
            "risk_amount": num(risk_amount, "0.01"),
            "executable_now": num(money(w_approved * multiplier), "0.01"),
            "multiplier": num(multiplier, "0.01"),
            "slices": [num(part, "0.01") for part in slices],
            "entry_lines": lines,
            "tier_preview": tier_preview,
            "notes": notes,
        }
        return problems, info

    def _reentry_gate(self, data: dict, prior: PositionView, market_price: Decimal | None) -> None:
        if prior.cooling_kind == "fundamental" and len((data.get("new_fact") or "").strip()) < 8:
            raise ServiceError("基本面证伪之后，必须写下新的可核验事实，仅价格上涨不算")
        if not data.get("industry_ok") or not data.get("fundamental_ok"):
            raise ServiceError("重新准入需要确认行业没有继续恶化，并且基本面复核通过")
        if prior.breakdown is not None and (market_price is None or market_price < prior.breakdown):
            raise ServiceError("价格尚未重新站上前次破位位")

    def _guard_buy(self, bundle, plan, instrument, view: PositionView, day, price, amount, vwap, reason, breach) -> None:
        if breach:
            return
        assessed = bundle["assessed"]
        if assessed["halt_active"]:
            raise ServiceError("新交易已停止")
        if assessed["effective"] == "defensive":
            raise ServiceError("防守状态原则上禁止新建仓")
        if cooling_buy_blocked(day, view.cooling_until):
            raise ServiceError("冷静期内禁止买入")
        params = bundle["params"]
        if chase_blocked(price, vwap, params):
            raise ServiceError(f"价格偏离当日 VWAP 超过 {pct_text(params.chase_multiple - 1)}，不追单")
        for other_plan, other_inst, _other_view in bundle["built"]:
            if other_inst["id"] == instrument["id"]:
                continue
            bought = any(
                row["plan_id"] == other_plan["id"] and row["side"] == "buy" and row["trade_date"] == day.isoformat()
                for row in bundle["fills"]
            )
            if bought and correlated(instrument["industry"], instrument["theme"], other_inst["industry"], other_inst["theme"]):
                raise ServiceError("同一日不能同时扩大多个高度相关标的的仓位")
        if reason == "reentry":
            if plan["fundamental_veto"] or view.p0_cancelled:
                raise ServiceError("P0 取消或重大否决之后，不能在原计划里买回")
            if view.cooling_until is None or cooling_buy_blocked(day, view.cooling_until):
                raise ServiceError("冷静期尚未结束")
            if not plan["industry_ok"] or not plan["fundamental_ok"]:
                raise ServiceError("重新准入需要确认行业没有继续恶化，并且基本面复核通过")
            if view.tier >= 1 or (view.breakdown and (view.last_price is None or view.last_price < view.breakdown)):
                raise ServiceError("价格尚未重新站上前次破位位")
            room = dec(plan["reentry_w"]) - view.reentry_spent
            if amount > room + Decimal("0.05"):
                raise ServiceError("超过重新准入批准的金额")
            return
        if reason != "entry":
            raise ServiceError("买入原因只能是计划建仓或重新准入")
        if view.tier >= 1:
            raise ServiceError("已触发减仓，不能加仓")
        if view.entry_state != "open":
            raise ServiceError(buy_state_message(view.entry_state, params))
        if amount > view.next_buy_amount + Decimal("0.05"):
            raise ServiceError("超过当日计划额度")
        schedule_days = sorted(
            {
                date.fromisoformat(row["trade_date"])
                for row in bundle["fills"]
                if row["plan_id"] == plan["id"] and row["side"] == "buy" and row["reason"] != "reentry"
            }
        )
        if view.p0 is not None and schedule_days and day != schedule_days[0]:
            if price >= view.p0 * params.p0_up:
                raise ServiceError(f"相对 P0 上涨达到 {pct_text(params.p0_up - 1)}，停止剩余建仓")
            if price <= view.p0 * params.p0_cancel:
                raise ServiceError(f"相对 P0 下跌达到 {pct_text(1 - params.p0_cancel)}，取消未完成建仓")
            if price <= view.p0 * params.p0_pause:
                raise ServiceError(f"相对 P0 收盘下跌达到 {pct_text(1 - params.p0_pause)}，暂停剩余建仓")

    def _guard_sell(self, view: PositionView, plan, shares: Decimal, reason: str, breach: bool, params: RuleParams) -> None:
        if shares > view.shares + Decimal("0.01"):
            raise ServiceError("不能卖出超过持仓的股数")
        if breach:
            return
        tolerance = max(params.sell_tolerance_shares, view.original_shares * params.sell_tolerance_pct)
        if reason == "rebalance":
            if view.overweight_shares <= 0:
                raise ServiceError("当前没有超过资产上限，不能按再平衡卖出")
            if shares > view.overweight_shares + tolerance:
                raise ServiceError("再平衡卖出超过超限股数")
            return
        if reason == "veto":
            if not plan["fundamental_veto"]:
                raise ServiceError("请先登记重大否决")
            return
        wanted = {"tier1": 1, "tier2": 2, "tier3": 3}.get(reason)
        if wanted is None:
            raise ServiceError("规则外卖出必须明确记为规则外")
        if view.tier <= 0:
            raise ServiceError("当前回撤没有触发卖出档位")
        if wanted != view.tier:
            raise ServiceError("跳空越过多档时，应按实际触及的最高档一次卖出")
        if shares > view.sell_need + tolerance:
            raise ServiceError("卖出股数超过本档应卖数量")

    def _active_rule_row(self, conn) -> dict:
        row = conn.execute(
            "SELECT * FROM rule_versions WHERE active = 1 ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            row = conn.execute("SELECT * FROM rule_versions ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            raise ServiceError("还没有规则版本")
        return dict(row)

    def _active_params(self, conn) -> RuleParams:
        row = self._active_rule_row(conn)
        return RuleParams.from_dict(json.loads(row["params_json"]))

    def _bundle(self, conn, day: date) -> dict:
        params = self._active_params(conn)
        rule_row = self._active_rule_row(conn)
        account = dict(conn.execute("SELECT * FROM account WHERE id = 1").fetchone())
        assessed = assess_account(
            intent=account["regime_intent"],
            nav=dec(account["nav"]),
            peak=dec(account["nav_peak"]),
            halt_until=date.fromisoformat(account["halt_new_until"]) if account["halt_new_until"] else None,
            as_of=day,
            trend_weakened=bool(account["trend_weakened"]),
            assumption_failed=bool(account["assumption_failed"]),
            special_started=date.fromisoformat(account["special_started_on"]) if account["special_started_on"] else None,
            params=params,
        )
        instruments = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM instruments")}
        plans = [dict(row) for row in conn.execute("SELECT * FROM plans ORDER BY id")]
        fills = [dict(row) for row in conn.execute("SELECT * FROM fills ORDER BY id")]
        marks = [dict(row) for row in conn.execute("SELECT * FROM marks ORDER BY id")]
        corps = [dict(row) for row in conn.execute("SELECT * FROM corporate_actions ORDER BY id")]
        built = []
        for plan in plans:
            instrument = instruments[plan["instrument_id"]]
            view = build_position(
                buys=[self._lot(row) for row in fills if row["plan_id"] == plan["id"] and row["side"] == "buy"],
                sells=[self._lot(row) for row in fills if row["plan_id"] == plan["id"] and row["side"] == "sell"],
                marks=[
                    Mark(date.fromisoformat(row["trade_date"]), dec(row["price"]), row["kind"], row["id"])
                    for row in marks
                    if row["plan_id"] == plan["id"]
                ],
                corps=[
                    Corp(date.fromisoformat(row["action_date"]), dec(row["price_factor"]), dec(row["share_factor"]))
                    for row in corps
                    if row["instrument_id"] == instrument["id"]
                ],
                as_of=day,
                w_approved=dec(plan["w_approved"]),
                entry_days=int(plan["entry_days"]),
                regime=assessed["effective"],
                nav=dec(account["nav"]),
                asset_cap=params.asset_cap(instrument["asset_type"]),
                abandoned=bool(plan["abandoned"]),
                structure_ok=bool(plan["structure_ok"]),
                up_review_ok=bool(plan["up_review_ok"]),
                fundamental_veto=bool(plan["fundamental_veto"]),
                reference_price=dec(plan["reference_price"]) if plan["reference_price"] else None,
                params=params,
            )
            built.append((plan, instrument, view))
        return {
            "account": account,
            "assessed": assessed,
            "instruments": instruments,
            "fills": fills,
            "marks": marks,
            "corps": corps,
            "built": built,
            "as_of": day,
            "params": params,
            "rule": rule_row,
        }

    def _public_snapshot(self, day: date, bundle: dict, weekly: list[dict], notes: list[dict], nav_points) -> dict:
        account = bundle["account"]
        assessed = bundle["assessed"]
        nav = dec(account["nav"])
        plans_public = []
        action_input = []
        trades: list[ClosedTrade] = []
        slippages: list[Decimal] = []
        off_rule = 0
        fill_count = 0
        gross = Decimal("0")
        for plan, instrument, view in bundle["built"]:
            plan_fills = [row for row in bundle["fills"] if row["plan_id"] == plan["id"] and row["trade_date"] <= day.isoformat()]
            plan_marks = [row for row in bundle["marks"] if row["plan_id"] == plan["id"] and row["trade_date"] <= day.isoformat()]
            fill_count += len(plan_fills)
            off_rule += sum(1 for row in plan_fills if row["off_rule"])
            for row in plan_fills:
                if row["slippage"] not in (None, ""):
                    slippages.append(dec(row["slippage"]))
            gross += view.market_value
            high = is_high_vol(instrument["asset_type"], bool(instrument["high_vol"]))
            meta = {
                "id": plan["id"],
                "code": instrument["code"],
                "name": instrument["name"],
                "industry": instrument["industry"],
                "theme": instrument["theme"],
                "high_vol": high,
                "asset_type": instrument["asset_type"],
                "fundamental_veto": bool(plan["fundamental_veto"]),
            }
            action_input.append((meta, view))
            if view.flat_date is not None and view.realized_pnl is not None:
                trades.append(
                    ClosedTrade(
                        plan_id=plan["id"],
                        code=instrument["code"],
                        name=instrument["name"],
                        pnl=view.realized_pnl,
                        flat_date=view.flat_date,
                        missed=dec(plan["missed_rebound"]) if plan["missed_rebound"] not in (None, "") else None,
                        off_rule_fills=sum(1 for row in plan_fills if row["off_rule"]),
                    )
                )
            plans_public.append(self._public_plan(plan, instrument, view, plan_fills, plan_marks, nav, high, bundle["params"]))
        warning_days = [day]
        for _meta, view in action_input:
            if view.cooling_until:
                warning_days.append(view.cooling_until)
        account_public = {
            "nav": num(nav, "0.01"),
            "cash": num(dec(account["cash"]), "0.01"),
            "nav_peak": num(dec(account["nav_peak"]), "0.01"),
            "peak_date": account["peak_date"],
            "drawdown": num(assessed["drawdown"], "0.000001"),
            "regime_intent": account["regime_intent"],
            "regime_intent_label": REGIME_LABELS[account["regime_intent"]],
            "effective_regime": assessed["effective"],
            "effective_regime_label": REGIME_LABELS[assessed["effective"]],
            "regime_cap": num(assessed["cap"], "0.01"),
            "regime_evidence": account["regime_evidence"],
            "special_reason": account["special_reason"],
            "special_exit": account["special_exit"],
            "special_started_on": account["special_started_on"],
            "special_last_day": iso(assessed["special_last"]),
            "trend_weakened": bool(account["trend_weakened"]),
            "assumption_failed": bool(account["assumption_failed"]),
            "risk_budget_pct": num(dec(account["risk_budget_pct"]), "0.000001"),
            "halt_new_until": account["halt_new_until"],
            "halt_active": assessed["halt_active"],
            "regime_reasons": assessed["reasons"],
            "suggested_nav": num(money(dec(account["cash"]) + gross), "0.01"),
            "calendar_warning": calendar_warning(warning_days),
        }
        params = bundle["params"]
        report = quarterly_report(
            trades,
            off_rule_fills=off_rule,
            total_fills=fill_count,
            nav_points=nav_points,
            slippages=slippages,
            params=params,
        )
        recent = []
        for plan, instrument, _view in reversed(bundle["built"]):
            for row in reversed([item for item in bundle["fills"] if item["plan_id"] == plan["id"]]):
                if row["trade_date"] <= day.isoformat():
                    recent.append(self._public_fill(row, instrument))
        recent = recent[:30]
        return {
            "as_of": day.isoformat(),
            "version": bundle["rule"]["name"],
            "effective_on": bundle["rule"]["created_at"][:10],
            "priority": " > ".join(HANDBOOK["priority"]),
            "disclaimer": HANDBOOK["disclaimer"],
            "account": account_public,
            "portfolio": self._portfolio(nav, plans_public),
            "actions": build_actions(
                day,
                {
                    "nav": nav,
                    "cash": dec(account["cash"]),
                    "effective": assessed["effective"],
                    "intent": account["regime_intent"],
                    "cap": assessed["cap"],
                    "halt_active": assessed["halt_active"],
                    "halt_until": date.fromisoformat(account["halt_new_until"]) if account["halt_new_until"] else None,
                    "reasons": assessed["reasons"],
                    "drawdown": assessed["drawdown"],
                    "calendar_warning": account_public["calendar_warning"],
                },
                action_input,
                params,
            ),
            "plans": plans_public,
            "instruments": [
                self._public_instrument(row, params) for row in bundle["instruments"].values()
            ],
            "rule": self._public_rule(bundle["rule"], params),
            "recent_fills": recent,
            "weekly": [
                {
                    "id": row["id"],
                    "week_ending": row["week_ending"],
                    "regime": row["regime"],
                    "regime_label": REGIME_LABELS.get(row["regime"], row["regime"]),
                    "exposure_note": row["exposure_note"],
                    "correlation_note": row["correlation_note"],
                    "decision": row["decision"],
                    "created_at": row["created_at"],
                }
                for row in weekly
            ],
            "quarterly": self._public_quarterly(report),
            "rule_notes": notes,
        }

    def _portfolio(self, nav: Decimal, plans: list[dict]) -> dict:
        industry: dict[str, Decimal] = {}
        theme: dict[str, Decimal] = {}
        high = Decimal("0")
        gross = Decimal("0")
        for plan in plans:
            value = dec(plan["view"]["market_value"])
            gross += value
            if value <= 0:
                continue
            if plan["industry"]:
                industry[plan["industry"]] = industry.get(plan["industry"], Decimal("0")) + value
            if plan["theme"]:
                theme[plan["theme"]] = theme.get(plan["theme"], Decimal("0")) + value
            if plan["high_vol"]:
                high += value

        def groups(source: dict[str, Decimal]) -> list[dict]:
            return [
                {
                    "name": name,
                    "value": num(value, "0.01"),
                    "weight": num(value / nav, "0.000001") if nav > 0 else None,
                }
                for name, value in sorted(source.items(), key=lambda item: item[1], reverse=True)
            ]

        return {
            "gross_value": num(gross, "0.01"),
            "gross_weight": num(gross / nav, "0.000001") if nav > 0 else None,
            "industries": groups(industry),
            "themes": groups(theme),
            "high_vol_value": num(high, "0.01"),
            "high_vol_weight": num(high / nav, "0.000001") if nav > 0 else None,
            "industry_cap": 0.35,
            "high_vol_cap": 0.2,
        }

    def _public_plan(self, plan, instrument, view: PositionView, fills, marks, nav: Decimal, high: bool, params: RuleParams) -> dict:
        return {
            "id": plan["id"],
            "instrument_id": instrument["id"],
            "code": instrument["code"],
            "name": instrument["name"],
            "asset_type": instrument["asset_type"],
            "asset_label": ASSET_LABELS[instrument["asset_type"]],
            "industry": instrument["industry"],
            "theme": instrument["theme"],
            "high_vol": high,
            "asset_cap": float(params.asset_cap(instrument["asset_type"])),
            "thesis": plan["thesis"],
            "catalyst": plan["catalyst"],
            "risks": json.loads(plan["risks_json"]),
            "invalidation": plan["invalidation"],
            "horizon": plan["horizon"],
            "regime_snapshot": plan["regime_snapshot"],
            "w_approved": num(dec(plan["w_approved"]), "0.01"),
            "w_max": num(dec(plan["w_max"]), "0.01"),
            "entry_days": plan["entry_days"],
            "reference_price": num(dec(plan["reference_price"]), "0.0001") if plan["reference_price"] else None,
            "abandoned": bool(plan["abandoned"]),
            "structure_ok": bool(plan["structure_ok"]),
            "up_review_ok": bool(plan["up_review_ok"]),
            "fundamental_veto": bool(plan["fundamental_veto"]),
            "veto_note": plan["veto_note"],
            "industry_ok": bool(plan["industry_ok"]),
            "fundamental_ok": bool(plan["fundamental_ok"]),
            "reentry_w": num(dec(plan["reentry_w"]), "0.01"),
            "new_fact": plan["new_fact"],
            "missed_rebound": num(dec(plan["missed_rebound"]), "0.01") if plan["missed_rebound"] not in (None, "") else None,
            "created_at": plan["created_at"],
            "weight": num(view.market_value / nav, "0.000001") if nav > 0 else None,
            "view": self._public_view(view, params),
            "fills": [self._public_fill(row, instrument) for row in fills],
            "marks": [
                {
                    "id": row["id"],
                    "trade_date": row["trade_date"],
                    "price": num(dec(row["price"]), "0.0001"),
                    "source": row["source"],
                    "kind": row["kind"],
                    "note": row["note"],
                }
                for row in marks
            ],
        }

    def _public_view(self, view: PositionView, params: RuleParams) -> dict:
        return {
            "entry_state": view.entry_state,
            "entry_label": ENTRY_LABELS.get(view.entry_state, view.entry_state),
            "next_buy_amount": num(view.next_buy_amount, "0.01"),
            "slices": [num(part, "0.01") for part in view.slices],
            "slice_index": view.slice_index,
            "slice_in_progress": view.slice_in_progress,
            "allowed_total": num(view.allowed_total, "0.01"),
            "filled_amount": num(view.filled_amount, "0.01"),
            "shares": num(view.shares, "0.0001"),
            "original_shares": num(view.original_shares, "0.0001"),
            "sold_shares": num(view.sold_shares, "0.0001"),
            "p0": num(view.p0, "0.0001"),
            "c": num(view.c, "0.0001"),
            "h": num(view.h, "0.0001"),
            "r": num(view.r, "0.0001"),
            "last_price": num(view.last_price, "0.0001"),
            "last_date": iso(view.last_date),
            "last_kind": view.last_kind,
            "close_price": num(view.close_price, "0.0001"),
            "drawdown": num(view.drawdown, "0.000001"),
            "tier": view.tier,
            "tier_prices": {
                "d10": num(view.tier_prices.get(1), "0.0001"),
                "d15": num(view.tier_prices.get(2), "0.0001"),
                "d20": num(view.tier_prices.get(3), "0.0001"),
            },
            "sell_need": num(view.sell_need, "0.0001"),
            "lines": {key: num(value, "0.0001") for key, value in view.lines.items()} if view.lines else None,
            "lines_preview": view.lines_preview,
            "cooling_kind": view.cooling_kind,
            "cooling_start": iso(view.cooling_start),
            "cooling_until": iso(view.cooling_until),
            "cooling_active": view.cooling_active,
            "breakdown": num(view.breakdown, "0.0001"),
            "p0_cancelled": view.p0_cancelled,
            "market_value": num(view.market_value, "0.01"),
            "profit_band": view.profit_band,
            "profit_label": band_label(view.profit_band, params),
            "protection_floor": num(view.protection_floor, "0.0001"),
            "overweight_shares": num(view.overweight_shares, "0.0001"),
            "rebalance_due": iso(view.rebalance_due),
            "rebalance_overdue": view.rebalance_overdue,
            "realized_pnl": num(view.realized_pnl, "0.01"),
            "flat_date": iso(view.flat_date),
            "unrealized_pnl": num(view.unrealized_pnl, "0.01"),
            "reentry_spent": num(view.reentry_spent, "0.01"),
            "await_close": view.await_close,
            "warnings": view.warnings,
        }

    def _public_fill(self, row, instrument) -> dict:
        return {
            "id": row["id"],
            "plan_id": row["plan_id"],
            "code": instrument["code"],
            "name": instrument["name"],
            "side": row["side"],
            "trade_date": row["trade_date"],
            "session": row["session"],
            "price": num(dec(row["price"]), "0.0001"),
            "shares": num(dec(row["shares"]), "0.0001"),
            "amount": num(dec(row["amount"]), "0.01"),
            "vwap": num(dec(row["vwap"]), "0.0001") if row["vwap"] not in (None, "") else None,
            "reason": row["reason"],
            "slippage": num(dec(row["slippage"]), "0.0001") if row["slippage"] not in (None, "") else None,
            "off_rule": bool(row["off_rule"]),
            "off_rule_reason": row["off_rule_reason"],
            "note": row["note"],
        }

    def _public_instrument(self, row, params: RuleParams) -> dict:
        return {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "asset_type": row["asset_type"],
            "asset_label": ASSET_LABELS[row["asset_type"]],
            "industry": row["industry"],
            "theme": row["theme"],
            "high_vol": is_high_vol(row["asset_type"], bool(row["high_vol"])),
            "asset_cap": float(params.asset_cap(row["asset_type"])),
            "liquidity_note": row["liquidity_note"],
        }

    def _public_quarterly(self, report: dict) -> dict:
        stats = report["stats"]
        public_stats = None
        if stats is not None:
            public_stats = {
                "win_rate": num(stats["win_rate"], "0.000001"),
                "avg_win": num(stats["avg_win"], "0.01"),
                "avg_loss": num(stats["avg_loss"], "0.01"),
                "payoff": num(stats["payoff"], "0.0001") if stats["payoff"] is not None else None,
                "expectancy": num(stats["expectancy"], "0.01"),
                "max_consecutive_losses": stats["max_consecutive_losses"],
                "max_account_drawdown": num(stats["max_account_drawdown"], "0.000001")
                if stats["max_account_drawdown"] is not None
                else None,
                "missed_rebound": num(stats["missed_rebound"], "0.01") if stats["missed_rebound"] is not None else None,
                "missed_coverage": stats["missed_coverage"],
                "avg_slippage": num(stats["avg_slippage"], "0.0001") if stats["avg_slippage"] is not None else None,
                "off_rule_ratio": num(stats["off_rule_ratio"], "0.000001"),
                "expectancy_positive": stats["expectancy_positive"],
                "off_rule_below_5pct": stats["off_rule_below_5pct"],
            }
        return {
            "evaluation_ready": report["evaluation_ready"],
            "progress": report["progress"],
            "required": report["required"],
            "off_rule_count": report["off_rule_count"],
            "fill_count": report["fill_count"],
            "reminder": report["reminder"],
            "stats": public_stats,
            "closed_trades": [
                {
                    "plan_id": trade["plan_id"],
                    "code": trade["code"],
                    "name": trade["name"],
                    "pnl": num(trade["pnl"], "0.01"),
                    "flat_date": trade["flat_date"].isoformat(),
                    "missed": num(trade["missed"], "0.01") if trade["missed"] is not None else None,
                    "off_rule_fills": trade["off_rule_fills"],
                }
                for trade in report["closed_trades"]
            ],
        }

    def _buckets(self, bundle) -> list[Bucket]:
        buckets = []
        for _plan, instrument, view in bundle["built"]:
            if view.market_value <= 0:
                continue
            buckets.append(
                Bucket(
                    instrument_id=instrument["id"],
                    market_value=view.market_value,
                    industry=instrument["industry"],
                    theme=instrument["theme"],
                    high_vol=is_high_vol(instrument["asset_type"], bool(instrument["high_vol"])),
                    asset_type=instrument["asset_type"],
                )
            )
        return buckets

    def _find(self, bundle, plan_id: int):
        for item in bundle["built"]:
            if item[0]["id"] == plan_id:
                return item
        raise ServiceError("找不到交易计划")

    def _plan_row(self, conn, plan_id: int) -> dict:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        if row is None:
            raise ServiceError("找不到交易计划")
        return dict(row)

    def _lot(self, row) -> Lot:
        return Lot(
            date.fromisoformat(row["trade_date"]),
            dec(row["price"]),
            dec(row["shares"]),
            dec(row["amount"]),
            row["reason"],
            row["id"],
        )
