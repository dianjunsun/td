import { useEffect, useState } from "react";
import type { Gate } from "../App";
import type { RuleParams } from "../types";
import { api } from "../api";
import { ASSETS } from "../format";

type Version = {
  id: number;
  name: string;
  note: string;
  created_at: string;
  active: boolean;
  params: RuleParams;
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

export function RulesPage({ gate }: { gate: Gate }) {
  const [versions, setVersions] = useState<Version[]>([]);
  const [params, setParams] = useState<RuleParams>(gate.snap.rule.params);
  const [name, setName] = useState("自定义");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api<{ versions: Version[] }>("/api/rules").then((data) => setVersions(data.versions)).catch((error) => gate.report(error));
  }, [gate.snap.rule.id]);

  function patch(next: Partial<RuleParams>) {
    setParams({ ...params, ...next });
  }

  async function save() {
    setSaving(true);
    try {
      await api("/api/rules", { method: "POST", body: JSON.stringify({ name, note: "", params }) });
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
        <h2>容受波动</h2>
        <p className="hint">相对建仓成本。现价还在这条线之上，就当作正常波动。</p>
        <div className="grid">
          <PercentField label="下跌仍可持有" value={1 - params.p0_pause} onChange={(value) => patch({ p0_pause: 1 - value })} />
          <PercentField label="下跌视为超出" value={1 - params.p0_cancel} onChange={(value) => patch({ p0_cancel: 1 - value })} />
        </div>
      </section>

      <section className="card stack">
        <h2>容受回撤</h2>
        <p className="hint">先相对成本。盈利超过下面的幅度之后，改用之后的最高价计算回撤。每一档是从锚点向下的幅度，以及到这一档时还留多少仓。</p>
        <div className="grid">
          <PercentField label="改用最高价的盈利" value={params.anchor_multiple - 1} onChange={(value) => patch({ anchor_multiple: 1 + value })} />
          {params.tier_drawdowns.map((value, index) => (
            <PercentField key={`d${index}`} label={`第 ${index + 1} 档回撤`} value={value} onChange={(next) => {
              patch({ tier_drawdowns: params.tier_drawdowns.map((item, itemIndex) => itemIndex === index ? next : item) });
            }} />
          ))}
          {params.tier_fractions.map((value, index) => (
            <PercentField key={`f${index}`} label={`第 ${index + 1} 档卖到剩余`} value={1 - value} onChange={(next) => {
              patch({ tier_fractions: params.tier_fractions.map((item, itemIndex) => itemIndex === index ? 1 - next : item) });
            }} />
          ))}
        </div>
        <p className="hint">卖到剩余 0% 就是清仓。默认第一档回撤 10% 卖到一半，15% 卖到四分之一，20% 清仓。</p>
      </section>

      <section className="card stack">
        <h2>股票类型仓位</h2>
        <p className="hint">这一类股票的市值占账户的上限。只用来对照，记账本身不受它拦截。</p>
        <div className="grid">
          {ASSETS.map(([key, label]) => (
            <PercentField key={key} label={label} value={params.asset_caps[key]} onChange={(value) => patch({ asset_caps: { ...params.asset_caps, [key]: value } })} />
          ))}
        </div>
        <label>版本名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
        <button className="btn" disabled={saving} onClick={save}>保存并生效</button>
      </section>

      {versions.length > 1 ? (
        <section className="card stack">
          <h2>已保存的版本</h2>
          {versions.map((item) => (
            <div key={item.id} className="row">
              <span>{item.created_at.slice(0, 10)} · {item.name}{item.active ? " · 生效中" : ""}</span>
              {item.active ? null : <button className="btn secondary" disabled={saving} onClick={() => activate(item.id)}>改用此版本</button>}
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
}
