import { useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { money, pct } from "../format";

export function ReviewPage({ gate }: { gate: Gate }) {
  const [ending, setEnding] = useState(gate.asOf);
  const [exposure, setExposure] = useState("");
  const [correlation, setCorrelation] = useState("");
  const [decision, setDecision] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const quarterly = gate.snap.quarterly;
  const width = Math.min(100, (quarterly.progress / quarterly.required) * 100);

  async function saveWeek() {
    setSaving(true);
    try {
      await api("/api/reviews/weekly", {
        method: "POST",
        body: JSON.stringify({ week_ending: ending, exposure_note: exposure, correlation_note: correlation, decision }),
      });
      gate.report("");
      await gate.reload();
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  async function saveNote() {
    setSaving(true);
    try {
      await api("/api/rule-notes", { method: "POST", body: JSON.stringify({ note }) });
      setNote("");
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
        <h2>季度样本 {quarterly.progress} / {quarterly.required}</h2>
        <div className="bar"><span style={{ width: `${width}%` }} /></div>
        <p>{quarterly.reminder}</p>
        <p className="hint">规则外成交 {quarterly.off_rule_count} 笔 / 全部 {quarterly.fill_count} 笔。纪要只留记录。要改阈值，去「规则参数」另存一版。</p>
        {quarterly.stats ? (
          <div className="grid">
            <div>胜率 {pct(quarterly.stats.win_rate)}</div>
            <div>平均盈利 {money(quarterly.stats.avg_win)}</div>
            <div>平均亏损 {money(quarterly.stats.avg_loss)}</div>
            <div>盈亏比 {quarterly.stats.payoff ?? "—"}</div>
            <div>期望值 {money(quarterly.stats.expectancy)}</div>
            <div>最大连亏 {quarterly.stats.max_consecutive_losses}</div>
            <div>账户最大回撤 {pct(quarterly.stats.max_account_drawdown)}</div>
            <div>规则外比例 {pct(quarterly.stats.off_rule_ratio)} · {quarterly.stats.off_rule_below_5pct ? `低于 ${pct(quarterly.off_rule_limit)}` : `不低于 ${pct(quarterly.off_rule_limit)}`}</div>
            <div>冷静期错失 {quarterly.stats.missed_rebound == null ? "未记录" : money(quarterly.stats.missed_rebound)}（{quarterly.stats.missed_coverage}）</div>
          </div>
        ) : null}
        {quarterly.closed_trades.length ? (
          <table>
            <thead><tr><th>结束日</th><th>标的</th><th className="num">盈亏</th><th className="num">规则外</th></tr></thead>
            <tbody>
              {quarterly.closed_trades.map((trade) => (
                <tr key={trade.plan_id}><td>{trade.flat_date}</td><td>{trade.code} {trade.name}</td><td className="num">{money(trade.pnl)}</td><td className="num">{trade.off_rule_fills}</td></tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
      <section className="card stack">
        <h2>周度仓位决策</h2>
        <div className="grid">
          <label>周末日期<input type="date" value={ending} onChange={(event) => setEnding(event.target.value)} /></label>
          <label>暴露<textarea value={exposure} onChange={(event) => setExposure(event.target.value)} /></label>
          <label>相关性<textarea value={correlation} onChange={(event) => setCorrelation(event.target.value)} /></label>
          <label>决策<textarea value={decision} onChange={(event) => setDecision(event.target.value)} /></label>
        </div>
        <button className="btn" disabled={saving} onClick={saveWeek}>保存周报</button>
        {gate.snap.weekly.map((item) => (
          <div key={item.id} className="hint">{item.week_ending} · {item.regime_label} · {item.decision}</div>
        ))}
      </section>
      <section className="card stack">
        <h2>规则纪要</h2>
        <textarea value={note} onChange={(event) => setNote(event.target.value)} />
        <button className="btn secondary" disabled={saving} onClick={saveNote}>追加纪要</button>
        {gate.snap.rule_notes.map((item) => <p key={item.id} className="hint">{item.created_at.slice(0, 10)} · {item.note}</p>)}
      </section>
    </div>
  );
}
