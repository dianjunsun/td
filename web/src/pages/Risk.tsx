import { useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { money, pct, px, shares } from "../format";

export function RiskPage({ gate }: { gate: Gate }) {
  const [instrumentId, setInstrumentId] = useState(gate.snap.instruments[0]?.id || 0);
  const [day, setDay] = useState(gate.asOf);
  const [kind, setKind] = useState("split");
  const [priceFactor, setPriceFactor] = useState("0.5");
  const [shareFactor, setShareFactor] = useState("2");
  const [note, setNote] = useState("1 拆 2");
  const [saving, setSaving] = useState(false);
  const held = gate.snap.plans.filter((plan) => plan.view.shares > 0 || plan.view.original_shares > 0);

  async function saveAction() {
    setSaving(true);
    try {
      await api("/api/corporate-actions", {
        method: "POST",
        body: JSON.stringify({
          instrument_id: instrumentId,
          action_date: day,
          kind,
          price_factor: Number(priceFactor),
          share_factor: Number(shareFactor),
          note,
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
      <section className="card">
        <h2>持仓锚点</h2>
        <table>
          <thead>
            <tr>
              <th>标的</th><th className="num">股数</th><th className="num">市值</th><th className="num">权重</th>
              <th className="num">P0</th><th className="num">C</th><th className="num">H</th><th className="num">R</th>
              <th className="num">回撤</th><th>三档</th><th className="num">应卖</th>
            </tr>
          </thead>
          <tbody>
            {held.map((plan) => (
              <tr key={plan.id}>
                <td>{plan.code}<div className="hint">{plan.view.profit_label}</div></td>
                <td className="num">{shares(plan.view.shares)}</td>
                <td className="num">{money(plan.view.market_value)}</td>
                <td className="num">{pct(plan.weight)} / {pct(plan.asset_cap)}</td>
                <td className="num">{px(plan.view.p0)}</td>
                <td className="num">{px(plan.view.c)}</td>
                <td className="num">{px(plan.view.h)}</td>
                <td className="num">{px(plan.view.r)}</td>
                <td className="num">{pct(plan.view.drawdown)}</td>
                <td>{px(plan.view.tier_prices.d10)} / {px(plan.view.tier_prices.d15)} / {px(plan.view.tier_prices.d20)}</td>
                <td className="num">{shares(plan.view.sell_need)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {held.length === 0 ? <p className="hint">还没有持仓。价格按前复权理解，公司行为要在下面登记。</p> : null}
      </section>
      <section className="card stack">
        <h2>公司行为</h2>
        <p className="hint">除权日及之后的价格按新口径填写。系统只调整除权日之前的成交和收盘。拆股 1 拆 2：价格因子 0.5，股数因子 2。</p>
        <div className="grid">
          <label>标的
            <select value={instrumentId} onChange={(event) => setInstrumentId(Number(event.target.value))}>
              {gate.snap.instruments.map((item) => <option key={item.id} value={item.id}>{item.code} {item.name}</option>)}
            </select>
          </label>
          <label>除权日<input type="date" value={day} onChange={(event) => setDay(event.target.value)} /></label>
          <label>类型
            <select value={kind} onChange={(event) => setKind(event.target.value)}>
              <option value="dividend">分红</option>
              <option value="split">拆股</option>
              <option value="reverse_split">合股</option>
              <option value="rights">配股</option>
              <option value="bonus">送转</option>
            </select>
          </label>
          <label>价格因子<input value={priceFactor} onChange={(event) => setPriceFactor(event.target.value)} /></label>
          <label>股数因子<input value={shareFactor} onChange={(event) => setShareFactor(event.target.value)} /></label>
          <label>说明<input value={note} onChange={(event) => setNote(event.target.value)} /></label>
        </div>
        <button className="btn" disabled={saving || !instrumentId} onClick={saveAction}>登记公司行为</button>
      </section>
    </div>
  );
}
