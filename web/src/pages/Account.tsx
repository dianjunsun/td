import { useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { pct } from "../format";

export function AccountPage({ gate }: { gate: Gate }) {
  const account = gate.snap.account;
  const caps = gate.snap.rule.params.regime_caps;
  const regimes: [string, string][] = [
    ["defensive", `防守 · ${pct(caps.defensive)}`],
    ["neutral", `中性 · ${pct(caps.neutral)}`],
    ["aggressive", `积极 · ${pct(caps.aggressive)}`],
    ["special_aggressive", `特殊积极 · ${pct(caps.special_aggressive)}`],
  ];
  const [nav, setNav] = useState(String(account.nav || ""));
  const [cash, setCash] = useState(String(account.cash || ""));
  const [regime, setRegime] = useState(account.regime_intent);
  const [evidence, setEvidence] = useState(account.regime_evidence);
  const [risk, setRisk] = useState(String((account.risk_budget_pct || 0.015) * 100));
  const [reason, setReason] = useState(account.special_reason);
  const [exit, setExit] = useState(account.special_exit);
  const [trend, setTrend] = useState(account.trend_weakened);
  const [failed, setFailed] = useState(account.assumption_failed);
  const [saving, setSaving] = useState(false);

  async function save() {
    setSaving(true);
    try {
      await api("/api/account", {
        method: "PUT",
        body: JSON.stringify({
          nav: Number(nav),
          cash: Number(cash),
          regime_intent: regime,
          regime_evidence: evidence,
          special_reason: reason,
          special_exit: exit,
          trend_weakened: trend,
          assumption_failed: failed,
          risk_budget_pct: Number(risk) / 100,
          as_of: gate.asOf,
        }),
      });
      gate.report("");
      await gate.reload();
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="section">
      <section className="card stack">
        <h2>账户与闸门</h2>
        <p className="hint">成交不会自动改写净值。收盘后按真实净值更新，回撤才有依据。建议净值（现金 + 持仓市值）目前是 {account.suggested_nav.toLocaleString("zh-CN")}。</p>
        <div className="grid">
          <label>账户净值<input id="nav" value={nav} onChange={(event) => setNav(event.target.value)} /></label>
          <label>现金<input id="cash" value={cash} onChange={(event) => setCash(event.target.value)} /></label>
          <label>风险预算（%）<input id="risk" value={risk} onChange={(event) => setRisk(event.target.value)} /></label>
          <label>市场状态
            <select id="regime" value={regime} onChange={(event) => setRegime(event.target.value)}>
              {regimes.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label className="span-2">证据<textarea id="evidence" value={evidence} onChange={(event) => setEvidence(event.target.value)} /></label>
        </div>
        {regime === "special_aggressive" ? (
          <div className="grid">
            <label>特殊积极理由<textarea value={reason} onChange={(event) => setReason(event.target.value)} /></label>
            <label>退出条件<textarea value={exit} onChange={(event) => setExit(event.target.value)} /></label>
          </div>
        ) : null}
        <label className="check"><input type="checkbox" checked={trend} onChange={(event) => setTrend(event.target.checked)} />市场或行业趋势转弱</label>
        <label className="check"><input type="checkbox" checked={failed} onChange={(event) => setFailed(event.target.checked)} />核心假设失效</label>
        <div className="row">
          <button className="btn" disabled={saving} onClick={save}>保存账户</button>
          <button className="btn secondary" type="button" onClick={() => setNav(String(account.suggested_nav))}>用现金+持仓市值回填净值</button>
        </div>
        <p className="hint">常态风险预算 {pct(gate.snap.rule.risk_budget_default)}，最高 {pct(gate.snap.rule.risk_budget_max)}。特殊积极最长维持到 {account.special_last_day || "尚未开始"}。停机至 {account.halt_new_until || "无"}。</p>
      </section>
    </div>
  );
}
