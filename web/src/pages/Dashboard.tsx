import type { Gate } from "../App";
import { money, pct, shares } from "../format";

export function Dashboard({ gate }: { gate: Gate }) {
  const { snap } = gate;
  const account = snap.account;
  const groups = [
    ["danger", "必须执行"],
    ["warn", "暂停与冷静"],
    ["plan", "今日建仓"],
    ["info", "提示"],
  ] as const;
  return (
    <div className="section">
      <div className="grid">
        <div className="card"><div className="hint">净值</div><div className="stat">{money(account.nav)}</div></div>
        <div className="card"><div className="hint">现金</div><div className="stat">{money(account.cash)}</div></div>
        <div className="card">
          <div className="hint">自高点回撤</div>
          <div className="stat">{pct(account.drawdown)}</div>
          <div className="hint">高点 {money(account.nav_peak)}</div>
        </div>
        <div className="card">
          <div className="hint">生效闸门</div>
          <div className="stat">{account.effective_regime_label}</div>
          <div className="hint">总仓上限 {pct(account.regime_cap)} · 当前 {pct(snap.portfolio.gross_weight)}</div>
        </div>
      </div>
      {account.regime_reasons.map((reason) => <div key={reason} className="action warn"><strong>闸门调整</strong>{reason}</div>)}
      {account.calendar_warning ? <div className="action info"><strong>日历</strong>{account.calendar_warning}</div> : null}
      {groups.map(([level, title]) => {
        const items = snap.actions.filter((item) => item.level === level && item.code !== "regime" && item.code !== "calendar");
        if (!items.length) return null;
        return (
          <section key={level}>
            <h2>{title}</h2>
            <div className="actions">
              {items.map((item, index) => (
                <article key={`${item.code}-${item.plan_id}-${index}`} className={`action ${item.level}`}>
                  <strong>{item.title}</strong>
                  <div>{item.detail}</div>
                  {item.shares ? <div className="hint">建议股数 {shares(item.shares)}</div> : null}
                </article>
              ))}
            </div>
          </section>
        );
      })}
      {snap.actions.length === 0 ? <div className="card">今日没有必须执行的风控动作。</div> : null}
      <section className="card">
        <h2>最近成交</h2>
        {snap.recent_fills.length === 0 ? <p className="hint">还没有成交。</p> : (
          <table>
            <thead><tr><th>日期</th><th>标的</th><th>方向</th><th className="num">价格</th><th className="num">股数</th><th className="num">金额</th><th>原因</th></tr></thead>
            <tbody>
              {snap.recent_fills.map((fill) => (
                <tr key={fill.id}>
                  <td>{fill.trade_date}</td>
                  <td>{fill.code} {fill.name}</td>
                  <td>{fill.side === "buy" ? "买入" : "卖出"}{fill.off_rule ? " · 规则外" : ""}</td>
                  <td className="num">{money(fill.price)}</td>
                  <td className="num">{shares(fill.shares)}</td>
                  <td className="num">{money(fill.amount)}</td>
                  <td>{fill.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
