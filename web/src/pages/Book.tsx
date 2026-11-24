import type { Gate } from "../App";
import { money, pct } from "../format";

export function BookPage({ gate }: { gate: Gate }) {
  const book = gate.snap.portfolio;
  const account = gate.snap.account;
  return (
    <div className="section">
      <div className="grid">
        <div className="card"><div className="hint">总市值</div><div className="stat">{money(book.gross_value)}</div><div className="hint">占净值 {pct(book.gross_weight)} / 上限 {pct(account.regime_cap)}</div></div>
        <div className="card"><div className="hint">高波动合计</div><div className="stat">{pct(book.high_vol_weight)}</div><div className="hint">上限 {pct(book.high_vol_cap)}</div></div>
        <div className="card"><div className="hint">行业或主题上限</div><div className="stat">{pct(book.industry_cap)}</div></div>
        <div className="card"><div className="hint">现金</div><div className="stat">{money(account.cash)}</div></div>
      </div>
      <section className="card">
        <h2>行业</h2>
        <Group rows={book.industries} cap={book.industry_cap} />
      </section>
      <section className="card">
        <h2>主题</h2>
        <Group rows={book.themes} cap={book.industry_cap} />
      </section>
    </div>
  );
}

function Group({ rows, cap }: { rows: { name: string; value: number; weight: number | null }[]; cap: number }) {
  if (!rows.length) return <p className="hint">还没有持仓。</p>;
  return (
    <table>
      <thead><tr><th>名称</th><th className="num">市值</th><th className="num">权重</th><th>相对 上限</th></tr></thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.name}>
            <td>{row.name}</td>
            <td className="num">{money(row.value)}</td>
            <td className="num">{pct(row.weight)}</td>
            <td>{(row.weight || 0) > cap ? "超过 35%" : "以内"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
