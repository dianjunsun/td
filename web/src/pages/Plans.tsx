import { useEffect, useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { ASSETS, money, pct } from "../format";
import type { Preview, Quote } from "../types";

export function PlansPage({ gate }: { gate: Gate }) {
  const [code, setCode] = useState("DEMO");
  const [name, setName] = useState("示例股份");
  const [asset, setAsset] = useState("large_cap");
  const [industry, setIndustry] = useState("消费");
  const [theme, setTheme] = useState("龙头");
  const [highVol, setHighVol] = useState(false);
  const [liquidityNote, setLiquidityNote] = useState("日均成交足以分批进出");
  const [quoteHint, setQuoteHint] = useState("");
  const [instrumentId, setInstrumentId] = useState(gate.snap.instruments[0]?.id || 0);
  const [thesis, setThesis] = useState("成熟公司现金流稳定");
  const [catalyst, setCatalyst] = useState("需求回升");
  const [risks, setRisks] = useState(["需求不及预期", "估值压缩", "行业政策"]);
  const [invalidation, setInvalidation] = useState("收盘跌破建仓逻辑或财务恶化");
  const [horizon, setHorizon] = useState("数月");
  const [w, setW] = useState("100000");
  const [days, setDays] = useState(5);
  const [reference, setReference] = useState("100");
  const [liquidityOk, setLiquidityOk] = useState(true);
  const [industryOk, setIndustryOk] = useState(false);
  const [fundamentalOk, setFundamentalOk] = useState(false);
  const [newFact, setNewFact] = useState("");
  const [marketPrice, setMarketPrice] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);

  useEffect(() => {
    if (!gate.draft) return;
    setCode(gate.draft.code);
    setName(gate.draft.name);
    setQuoteHint("");
    gate.setDraft(null);
  }, [gate.draft]);
  const [saving, setSaving] = useState(false);

  function payload() {
    return {
      instrument_id: Number(instrumentId),
      thesis, catalyst, risks, invalidation, horizon,
      w_approved: Number(w),
      entry_days: days,
      reference_price: reference ? Number(reference) : null,
      liquidity_ok: liquidityOk,
      industry_ok: industryOk,
      fundamental_ok: fundamentalOk,
      new_fact: newFact,
      market_price: marketPrice ? Number(marketPrice) : null,
      as_of: gate.asOf,
    };
  }

  async function addInstrument() {
    setSaving(true);
    try {
      const created = await api<{ id: number }>("/api/instruments", {
        method: "POST",
        body: JSON.stringify({ code, name, asset_type: asset, industry, theme, high_vol: highVol, liquidity_note: liquidityNote }),
      });
      setInstrumentId(created.id);
      gate.report("");
      await gate.reload();
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  async function quote() {
    try {
      setPreview(await api<Preview>("/api/plans/preview", { method: "POST", body: JSON.stringify(payload()) }));
      gate.report("");
    } catch (error) {
      gate.report(error);
    }
  }

  async function submit() {
    setSaving(true);
    try {
      const created = await api<{ id: number }>("/api/plans", { method: "POST", body: JSON.stringify(payload()) });
      gate.setSelected(created.id);
      gate.report("");
      await gate.reload();
      gate.go("trade");
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="section">
      <section className="card stack">
        <h2>标的</h2>
        <div className="grid">
          <label>代码<input id="code" value={code} onChange={(event) => setCode(event.target.value)} /></label>
          <label>名称<input id="name" value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label>资产类型
            <select id="asset" value={asset} onChange={(event) => setAsset(event.target.value)}>
              {ASSETS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>行业<input id="industry" value={industry} onChange={(event) => setIndustry(event.target.value)} /></label>
          <label>主题<input id="theme" value={theme} onChange={(event) => setTheme(event.target.value)} /></label>
          <label>流动性备注<input value={liquidityNote} onChange={(event) => setLiquidityNote(event.target.value)} /></label>
        </div>
        <label className="check"><input type="checkbox" checked={highVol} onChange={(event) => setHighVol(event.target.checked)} />计入高波动合计（上限 20%）</label>
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
              const quote = await api<Quote>(`/api/quotes/${encodeURIComponent(code.trim())}?source=${encodeURIComponent(gate.quoteSource)}`);
              setName(quote.name);
              setQuoteHint(`${quote.name} 最新 ${quote.price}，昨收 ${quote.prev_close || "—"}，${quote.source_label} ${quote.as_of}`);
              gate.report("");
            } catch (error) {
              gate.report(error);
            }
          }}>读取行情</button>
          <button className="btn" disabled={saving} onClick={addInstrument}>添加标的</button>
        </div>
        {quoteHint ? <p className="hint">{quoteHint}。资产类型仍要自己选，行情不知道它属于哪一类仓位。</p> : null}
      </section>
      <section className="card stack">
        <h2>新交易计划</h2>
        <label>标的
          <select value={instrumentId} onChange={(event) => setInstrumentId(Number(event.target.value))}>
            <option value={0}>选择标的</option>
            {gate.snap.instruments.map((item) => (
              <option key={item.id} value={item.id}>{item.code} {item.name} · {item.asset_label} · 上限 {pct(item.asset_cap)}</option>
            ))}
          </select>
        </label>
        <div className="grid">
          <label className="span-2">核心理由<textarea value={thesis} onChange={(event) => setThesis(event.target.value)} /></label>
          <label>催化<input value={catalyst} onChange={(event) => setCatalyst(event.target.value)} /></label>
          <label>持有期<input value={horizon} onChange={(event) => setHorizon(event.target.value)} /></label>
          {risks.map((risk, index) => (
            <label key={index}>风险 {index + 1}
              <input value={risk} onChange={(event) => setRisks(risks.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} />
            </label>
          ))}
          <label className="span-2">失效条件<textarea id="invalidation" value={invalidation} onChange={(event) => setInvalidation(event.target.value)} /></label>
          <label>批准仓位 W（元）<input id="w" value={w} onChange={(event) => setW(event.target.value)} /></label>
          <label>建仓天数
            <select value={days} onChange={(event) => setDays(Number(event.target.value))}>
              {gate.snap.rule.schedules.map((item) => <option key={item.days} value={item.days}>{item.label}</option>)}
            </select>
          </label>
          <label>参考价（预览 P0）<input value={reference} onChange={(event) => setReference(event.target.value)} /></label>
          <label>再次买入时的现价<input value={marketPrice} onChange={(event) => setMarketPrice(event.target.value)} /></label>
        </div>
        <label className="check"><input type="checkbox" checked={liquidityOk} onChange={(event) => setLiquidityOk(event.target.checked)} />流动性足以分批进出</label>
        <label className="check"><input type="checkbox" checked={industryOk} onChange={(event) => setIndustryOk(event.target.checked)} />行业没有继续恶化（冷静期后再买入时必填）</label>
        <label className="check"><input type="checkbox" checked={fundamentalOk} onChange={(event) => setFundamentalOk(event.target.checked)} />基本面已复核（冷静期后再买入时必填）</label>
        <label>推翻原证伪的新事实<textarea value={newFact} onChange={(event) => setNewFact(event.target.value)} /></label>
        <div className="row">
          <button className="btn secondary" type="button" onClick={quote}>试算仓位</button>
          <button className="btn" disabled={saving} onClick={submit}>提交计划</button>
        </div>
        {preview ? (
          <div className="hint">
            <div>W_max {money(preview.w_max)} · 资产上限 {money(preview.cap_amount)} · 风险路径 {money(preview.risk_amount)}</div>
            <div>当前闸门可执行 {money(preview.executable_now)} · 分日 {preview.slices.map((item) => money(item)).join(" / ")}</div>
            {preview.entry_lines ? <div>参考线：上涨暂停 {preview.entry_lines.up}，下跌暂停 {preview.entry_lines.pause}，取消 {preview.entry_lines.cancel}</div> : null}
            {preview.notes.map((note) => <div key={note}>{note}</div>)}
            {preview.errors.length ? <div>未通过：{preview.errors.join("；")}</div> : <div>字段和仓位都通过。</div>}
          </div>
        ) : null}
      </section>
      <section className="card">
        <h2>已有计划</h2>
        <table>
          <thead><tr><th>标的</th><th>逻辑</th><th className="num">W</th><th>状态</th><th>失效条件</th></tr></thead>
          <tbody>
            {gate.snap.plans.map((plan) => (
              <tr key={plan.id}>
                <td>{plan.code} {plan.name}</td>
                <td>{plan.thesis}</td>
                <td className="num">{money(plan.w_approved)}</td>
                <td>{plan.view.entry_label}</td>
                <td>{plan.invalidation}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
