import { useEffect, useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { money, pct, px, shares } from "../format";
import type { Quote } from "../types";

export function TradePage({ gate }: { gate: Gate }) {
  const plan = gate.snap.plans.find((item) => item.id === gate.selected) || gate.snap.plans[0];
  const [buyDate, setBuyDate] = useState(gate.asOf);
  const [session, setSession] = useState("am");
  const [buyPrice, setBuyPrice] = useState("100");
  const [buyShares, setBuyShares] = useState("200");
  const [vwap, setVwap] = useState("100");
  const [markDate, setMarkDate] = useState(gate.asOf);
  const [markPrice, setMarkPrice] = useState("130");
  const [markKind, setMarkKind] = useState("close");
  const [markSource, setMarkSource] = useState("手工");
  const [quoteHint, setQuoteHint] = useState("");
  const [sellDate, setSellDate] = useState(gate.asOf);
  const [sellPrice, setSellPrice] = useState("");
  const [sellShares, setSellShares] = useState("");
  const [sellReason, setSellReason] = useState("tier1");
  const [breach, setBreach] = useState(false);
  const [breachReason, setBreachReason] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setBuyDate(gate.asOf);
    setMarkDate(gate.asOf);
    setSellDate(gate.asOf);
  }, [gate.asOf]);

  if (!plan) return <div className="card">还没有计划。先到「交易计划」建一张。</div>;
  const view = plan.view;

  async function send(path: string, body: unknown, nextDay?: string) {
    setSaving(true);
    try {
      await api(path, { method: "POST", body: JSON.stringify(body) });
      if (nextDay) gate.setAsOf(nextDay);
      gate.report("");
      await gate.reload(nextDay);
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="split">
      <section className="card stack">
        <h2>计划</h2>
        {gate.snap.plans.map((item) => (
          <button key={item.id} className={`pick ${item.id === plan.id ? "active" : ""}`} onClick={() => gate.setSelected(item.id)}>
            {item.code} {item.name}
            <div className="hint">{item.view.entry_label} · {shares(item.view.shares)} 股</div>
          </button>
        ))}
      </section>
      <div className="section">
        <section className="card">
          <h2>{plan.code} {plan.name}</h2>
          <p className="hint">{plan.thesis} · 失效：{plan.invalidation}</p>
          <div className="grid">
            <div><div className="hint">P0</div><div className="stat">{px(view.p0)}</div></div>
            <div><div className="hint">C / H / R</div><div className="stat">{px(view.c)} / {px(view.h)} / {px(view.r)}</div></div>
            <div><div className="hint">回撤</div><div className="stat">{pct(view.drawdown)}</div></div>
            <div><div className="hint">建议卖出</div><div className="stat">{shares(view.sell_need)}</div></div>
          </div>
          <p className="hint">
            {view.lines ? `${view.lines_preview ? "参考" : "P0"}线：上涨 ${px(view.lines.up)}，暂停 ${px(view.lines.pause)}，取消 ${px(view.lines.cancel)}，站回 ${px(view.lines.reclaim)}。` : "还没有价格锚点。"}
            {" "}三档 {px(view.tier_prices.d10)} / {px(view.tier_prices.d15)} / {px(view.tier_prices.d20)}。
            {" "}{view.profit_label}
            {view.protection_floor != null ? `，保护价不低于 ${px(view.protection_floor)}` : ""}。
          </p>
          <p className="hint">今日还可买 {money(view.next_buy_amount)} · 已用 {money(view.filled_amount)} / 闸门允许 {money(view.allowed_total)} · 权重 {pct(plan.weight)}</p>
          <div className="row">
            <label>行情源
              <select value={gate.quoteSource} onChange={(event) => gate.setQuoteSource(event.target.value)}>
                {gate.quoteSources.map((item) => (
                  <option key={item.id} value={item.id} disabled={!item.ready}>{item.ready ? item.label : `${item.label}（未配置）`}</option>
                ))}
              </select>
            </label>
            <button className="btn secondary" type="button" onClick={async () => {
              try {
                const quote = await api<Quote>(`/api/quotes/${encodeURIComponent(plan.code)}?source=${encodeURIComponent(gate.quoteSource)}`);
                setBuyPrice(quote.price);
                if (quote.vwap) setVwap(quote.vwap);
                setMarkPrice(quote.price);
                setSellPrice(quote.price);
                setMarkSource(quote.source_label);
                setQuoteHint(`${quote.source_label} ${quote.as_of} 最新 ${quote.price}${quote.vwap ? `，估算 VWAP ${quote.vwap}` : ""}。填入后仍要点记录才会入账。`);
                gate.report("");
              } catch (error) {
                gate.report(error);
              }
            }}>读取行情</button>
          </div>
          {quoteHint ? <p className="hint">{quoteHint}</p> : null}
        </section>
        <section className="card stack">
          <h2>买入</h2>
          <div className="grid">
            <label>日期<input type="date" value={buyDate} onChange={(event) => setBuyDate(event.target.value)} /></label>
            <label>时段
              <select value={session} onChange={(event) => setSession(event.target.value)}>
                <option value="am">上午</option>
                <option value="pm">下午</option>
              </select>
            </label>
            <label>价格<input value={buyPrice} onChange={(event) => setBuyPrice(event.target.value)} /></label>
            <label>股数<input value={buyShares} onChange={(event) => setBuyShares(event.target.value)} /></label>
            <label>当日 VWAP<input value={vwap} onChange={(event) => setVwap(event.target.value)} /></label>
          </div>
          <label className="check"><input type="checkbox" checked={breach} onChange={(event) => setBreach(event.target.checked)} />记为规则外成交</label>
          {breach ? <label>规则外原因<input value={breachReason} onChange={(event) => setBreachReason(event.target.value)} /></label> : null}
          <button className="btn" disabled={saving} onClick={() => send(`/api/plans/${plan.id}/fills`, {
            side: "buy", trade_date: buyDate, session, price: Number(buyPrice), shares: Number(buyShares),
            vwap: vwap ? Number(vwap) : null, reason: "entry", record_breach: breach, off_rule_reason: breachReason,
          }, buyDate)}>记录买入</button>
        </section>
        <section className="card stack">
          <h2>收盘或盘中价</h2>
          <div className="grid">
            <label>日期<input type="date" value={markDate} onChange={(event) => setMarkDate(event.target.value)} /></label>
            <label>价格<input id="mark-price" value={markPrice} onChange={(event) => setMarkPrice(event.target.value)} /></label>
            <label>类型
              <select value={markKind} onChange={(event) => setMarkKind(event.target.value)}>
                <option value="close">收盘</option>
                <option value="intraday">盘中</option>
              </select>
            </label>
            <label>来源<input value={markSource} onChange={(event) => setMarkSource(event.target.value)} /></label>
          </div>
          <p className="hint">常规用收盘价确认。盘中只在已经触及 15% 第二档，或另有重大利空时执行。</p>
          <button className="btn" disabled={saving} onClick={() => send(`/api/plans/${plan.id}/marks`, {
            trade_date: markDate, price: Number(markPrice), source: markSource, kind: markKind,
          }, markDate)}>记录收盘价</button>
        </section>
        <section className="card stack">
          <h2>卖出</h2>
          <div className="grid">
            <label>日期<input type="date" value={sellDate} onChange={(event) => setSellDate(event.target.value)} /></label>
            <label>价格<input value={sellPrice} onChange={(event) => setSellPrice(event.target.value)} /></label>
            <label>股数<input id="sell-shares" value={sellShares} onChange={(event) => setSellShares(event.target.value)} /></label>
            <label>原因
              <select value={sellReason} onChange={(event) => setSellReason(event.target.value)}>
                <option value="tier1">第一档</option>
                <option value="tier2">第二档</option>
                <option value="tier3">第三档</option>
                <option value="rebalance">再平衡</option>
                <option value="veto">重大否决</option>
              </select>
            </label>
          </div>
          <div className="row">
            <button className="btn secondary" type="button" onClick={() => { setSellShares(String(view.sell_need)); setSellReason(view.tier === 2 ? "tier2" : view.tier === 3 ? "tier3" : "tier1"); }}>填入建议数量</button>
            <button className="btn sell" disabled={saving} onClick={() => send(`/api/plans/${plan.id}/fills`, {
              side: "sell", trade_date: sellDate, session: "pm", price: Number(sellPrice), shares: Number(sellShares), reason: sellReason,
            }, sellDate)}>记录卖出</button>
          </div>
        </section>
        <section className="card row">
          <button className="btn secondary" onClick={() => send(`/api/plans/${plan.id}/flags`, { structure_ok: true })}>确认成交结构已改善</button>
          <button className="btn secondary" onClick={() => send(`/api/plans/${plan.id}/flags`, { up_review_ok: true })}>确认上涨暂停已复核</button>
          <button className="btn secondary" onClick={() => send(`/api/plans/${plan.id}/abandon`, {})}>放弃剩余建仓</button>
          <button className="btn secondary" onClick={() => send(`/api/plans/${plan.id}/veto`, { note: "重大否决，直接清仓" })}>登记重大否决</button>
        </section>
        <section className="card">
          <h2>记录</h2>
          <table>
            <thead><tr><th>日期</th><th>类型</th><th className="num">价格</th><th className="num">股数</th><th>说明</th></tr></thead>
            <tbody>
              {plan.fills.map((fill) => (
                <tr key={`f${fill.id}`}><td>{fill.trade_date}</td><td>{fill.side === "buy" ? "买入" : "卖出"}</td><td className="num">{px(fill.price)}</td><td className="num">{shares(fill.shares)}</td><td>{fill.reason}{fill.off_rule ? " · 规则外" : ""}</td></tr>
              ))}
              {plan.marks.map((mark) => (
                <tr key={`m${mark.id}`}><td>{mark.trade_date}</td><td>{mark.kind === "close" ? "收盘" : "盘中"}</td><td className="num">{px(mark.price)}</td><td className="num">—</td><td>{mark.source}</td></tr>
              ))}
            </tbody>
          </table>
        </section>
      </div>
    </div>
  );
}
