import { useEffect, useState } from "react";
import type { Gate } from "../App";
import type { Handbook, RuleParams } from "../types";
import { api } from "../api";
import { pct } from "../format";

type Version = {
  id: number;
  name: string;
  note: string;
  created_at: string;
  active: boolean;
  params: RuleParams;
  path_loss: number;
  sections: { title: string; items: string[] }[];
};

function percent(value: number): string {
  if (!Number.isFinite(value)) return "";
  const shown = Math.round(value * 10000) / 100;
  return String(shown);
}

function fromPercent(text: string): number {
  return Number(text) / 100;
}

function PercentField({ label, value, onChange }: { label: string; value: number; onChange: (next: number) => void }) {
  return (
    <label>
      {label}（%）
      <input value={percent(value)} onChange={(event) => onChange(fromPercent(event.target.value))} />
    </label>
  );
}

function DayField({ label, value, onChange, unit = "交易日" }: { label: string; value: number; onChange: (next: number) => void; unit?: string }) {
  return (
    <label>
      {label}{unit ? `（${unit}）` : ""}
      <input value={String(value)} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

const ASSET_FIELDS: [string, string][] = [
  ["broad_etf", "宽基 ETF"],
  ["sector_etf", "行业 ETF"],
  ["large_cap", "大型成熟公司"],
  ["growth", "中小盘成长"],
  ["high_vol", "高波动 / 亏损"],
];

const REGIME_FIELDS: [string, string][] = [
  ["defensive", "防守总仓"],
  ["neutral", "中性总仓"],
  ["aggressive", "积极总仓"],
  ["special_aggressive", "特殊积极总仓"],
];

export function RulesPage({ gate, handbook }: { gate: Gate; handbook: Handbook | null }) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [params, setParams] = useState<RuleParams>(gate.snap.rule.params);
  const [name, setName] = useState("自定义");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [sections, setSections] = useState(handbook?.sections || []);

  useEffect(() => {
    api<{ versions: Version[] }>("/api/rules").then((data) => {
      setVersions(data.versions);
      const current = data.versions.find((item) => item.active);
      if (current) setSections(current.sections);
    }).catch((error) => gate.report(error));
  }, [gate.snap.rule.id]);

  function patch(next: Partial<RuleParams>) {
    setParams({ ...params, ...next });
  }

  async function save() {
    setSaving(true);
    try {
      const saved = await api<Version>("/api/rules", {
        method: "POST",
        body: JSON.stringify({ name, note, params }),
      });
      setSections(saved.sections);
      gate.report("");
      await gate.reload();
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  async function activate(id: number) {
    setSaving(true);
    try {
      const saved = await api<Version>(`/api/rules/${id}/activate`, { method: "POST" });
      setParams(saved.params);
      setSections(saved.sections);
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
        <h2>当前生效：{gate.snap.rule.name}</h2>
        <p className="hint">
          计算使用这一版。保存不会覆盖旧版本，已经记下来的成交也不改。风险路径亏损 {pct(gate.snap.rule.path_loss)}。
          手册里的禁止融资、禁止亏损加仓、买入前写失效条件，仍然是硬性要求。
        </p>
        <div className="grid">
          <label className="span-2">新版本名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
          <label className="span-2">修改说明<textarea value={note} onChange={(event) => setNote(event.target.value)} /></label>
        </div>
      </section>

      <section className="card stack">
        <h2>市场闸门</h2>
        <div className="grid">
          {REGIME_FIELDS.map(([key, label]) => (
            <PercentField key={key} label={label} value={params.regime_caps[key]} onChange={(value) => patch({ regime_caps: { ...params.regime_caps, [key]: value } })} />
          ))}
          <PercentField label="中性只执行 W 的" value={params.neutral_executable} onChange={(value) => patch({ neutral_executable: value })} />
          <DayField label="特殊积极最长" value={params.special_max_days} onChange={(value) => patch({ special_max_days: value })} />
        </div>
      </section>

      <section className="card stack">
        <h2>仓位上限</h2>
        <div className="grid">
          {ASSET_FIELDS.map(([key, label]) => (
            <PercentField key={key} label={label} value={params.asset_caps[key]} onChange={(value) => patch({ asset_caps: { ...params.asset_caps, [key]: value } })} />
          ))}
          <PercentField label="同行业或同主题" value={params.industry_cap} onChange={(value) => patch({ industry_cap: value })} />
          <PercentField label="高波动合计" value={params.high_vol_group_cap} onChange={(value) => patch({ high_vol_group_cap: value })} />
          <PercentField label="常态风险预算" value={params.risk_budget_default} onChange={(value) => patch({ risk_budget_default: value })} />
          <PercentField label="风险预算硬顶" value={params.risk_budget_max} onChange={(value) => patch({ risk_budget_max: value })} />
        </div>
        <p className="hint">风险路径按「这段仓位会亏这么多」加权。W_max 用风险预算除以加权亏损。</p>
        {params.path_legs.map((leg, index) => (
          <div className="grid" key={index}>
            <PercentField label={`路径 ${index + 1} 权重`} value={leg.weight} onChange={(value) => {
              const path_legs = params.path_legs.map((item, itemIndex) => itemIndex === index ? { ...item, weight: value } : item);
              patch({ path_legs });
            }} />
            <PercentField label={`路径 ${index + 1} 亏损`} value={leg.loss} onChange={(value) => {
              const path_legs = params.path_legs.map((item, itemIndex) => itemIndex === index ? { ...item, loss: value } : item);
              patch({ path_legs });
            }} />
          </div>
        ))}
        <label className="check">
          <input type="checkbox" checked={params.broad_etf_uses_cap_when_aggressive} onChange={(event) => patch({ broad_etf_uses_cap_when_aggressive: event.target.checked })} />
          积极状态下宽基直接用资产上限，不再按风险路径压缩
        </label>
      </section>

      <section className="card stack">
        <h2>建仓</h2>
        {params.schedules.map((weights, index) => (
          <div key={index} className="stack">
            <strong>{weights.length} 日</strong>
            <div className="grid">
              {weights.map((weight, day) => (
                <PercentField key={day} label={`第 ${day + 1} 日`} value={weight} onChange={(value) => {
                  const schedules = params.schedules.map((row, rowIndex) => rowIndex === index ? row.map((item, itemIndex) => itemIndex === day ? value : item) : row);
                  patch({ schedules });
                }} />
              ))}
            </div>
            <div className="row">
              <button className="btn secondary" type="button" onClick={() => {
                const schedules = params.schedules.map((row, rowIndex) => rowIndex === index ? [...row, row[row.length - 1] || 1] : row);
                patch({ schedules });
              }}>加一天</button>
              {weights.length > 1 ? (
                <button className="btn secondary" type="button" onClick={() => {
                  const schedules = params.schedules.map((row, rowIndex) => rowIndex === index ? row.slice(0, -1) : row);
                  patch({ schedules });
                }}>去掉最后一天</button>
              ) : null}
              {params.schedules.length > 1 ? (
                <button className="btn secondary" type="button" onClick={() => patch({ schedules: params.schedules.filter((_, rowIndex) => rowIndex !== index) })}>删除这套</button>
              ) : null}
            </div>
          </div>
        ))}
        <button className="btn secondary" type="button" onClick={() => patch({ schedules: [...params.schedules, [1]] })}>添加一套分日比例</button>
        <div className="grid">
          <PercentField label="上涨停止" value={params.p0_up - 1} onChange={(value) => patch({ p0_up: 1 + value })} />
          <PercentField label="下跌暂停" value={1 - params.p0_pause} onChange={(value) => patch({ p0_pause: 1 - value })} />
          <PercentField label="下跌取消" value={1 - params.p0_cancel} onChange={(value) => patch({ p0_cancel: 1 - value })} />
          <PercentField label="站回才恢复" value={1 - params.p0_reclaim} onChange={(value) => patch({ p0_reclaim: 1 - value })} />
          <PercentField label="偏离 VWAP 不追" value={params.chase_multiple - 1} onChange={(value) => patch({ chase_multiple: 1 + value })} />
          <DayField label="上涨后再企稳" value={params.spike_stable_days} onChange={(value) => patch({ spike_stable_days: value })} />
        </div>
      </section>

      <section className="card stack">
        <h2>卖出、冷静期和账户</h2>
        <div className="grid">
          {params.tier_drawdowns.map((value, index) => (
            <PercentField key={`d${index}`} label={`第 ${index + 1} 档回撤`} value={value} onChange={(next) => {
              const tier_drawdowns = params.tier_drawdowns.map((item, itemIndex) => itemIndex === index ? next : item);
              patch({ tier_drawdowns });
            }} />
          ))}
          {params.tier_fractions.map((value, index) => (
            <PercentField key={`f${index}`} label={`第 ${index + 1} 档卖到`} value={value} onChange={(next) => {
              const tier_fractions = params.tier_fractions.map((item, itemIndex) => itemIndex === index ? next : item);
              patch({ tier_fractions });
            }} />
          ))}
          <PercentField label="改用高水位的盈利" value={params.anchor_multiple - 1} onChange={(value) => patch({ anchor_multiple: 1 + value })} />
          <PercentField label="保护价不低于成本" value={params.profit_floor_multiple - 1} onChange={(value) => patch({ profit_floor_multiple: 1 + value })} />
          <PercentField label="不机械清仓的盈利" value={params.run_multiple - 1} onChange={(value) => patch({ run_multiple: 1 + value })} />
          <DayField label="减仓冷静期" value={params.cooling_reduction_days} onChange={(value) => patch({ cooling_reduction_days: value })} />
          <DayField label="清仓冷静期" value={params.cooling_exit_days} onChange={(value) => patch({ cooling_exit_days: value })} />
          <DayField label="再平衡期限" value={params.rebalance_days} onChange={(value) => patch({ rebalance_days: value })} />
          <DayField label="盘中直接执行的档位" unit="档" value={params.intraday_auto_tier} onChange={(value) => patch({ intraday_auto_tier: value })} />
          <PercentField label="账户回撤下调一级" value={params.account_dd_downgrade} onChange={(value) => patch({ account_dd_downgrade: value })} />
          <PercentField label="账户回撤进入防守" value={params.account_dd_defensive} onChange={(value) => patch({ account_dd_defensive: value })} />
          <PercentField label="账户回撤停止新交易" value={params.account_dd_halt} onChange={(value) => patch({ account_dd_halt: value })} />
          <DayField label="停机至少" value={params.halt_days} onChange={(value) => patch({ halt_days: value })} />
          <DayField label="统计样本至少" unit="笔" value={params.min_sample} onChange={(value) => patch({ min_sample: value })} />
          <PercentField label="规则外成交目标低于" value={params.off_rule_limit} onChange={(value) => patch({ off_rule_limit: value })} />
        </div>
        <p className="hint">第三档必须卖到原始持仓的 100%。盘中档位填 2，表示只有第二档及更深才在盘中执行。</p>
        <button className="btn" disabled={saving} onClick={save}>另存为生效版本</button>
      </section>

      <section className="card stack">
        <h2>版本</h2>
        {versions.map((item) => (
          <div key={item.id} className="row">
            <span>{item.created_at.slice(0, 10)} · {item.name}{item.active ? " · 生效中" : ""}</span>
            {item.note ? <span className="hint">{item.note}</span> : null}
            {item.active ? null : <button className="btn secondary" disabled={saving} onClick={() => activate(item.id)}>改用此版本</button>}
          </div>
        ))}
      </section>

      {sections.map((section) => (
        <section key={section.title} className="card">
          <h2>{section.title}</h2>
          <ul>{section.items.map((item) => <li key={item}>{item}</li>)}</ul>
        </section>
      ))}
    </div>
  );
}
