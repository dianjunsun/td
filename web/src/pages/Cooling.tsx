import { useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { px } from "../format";

export function CoolingPage({ gate }: { gate: Gate }) {
  const rows = gate.snap.plans.filter((plan) => plan.view.cooling_until);
  const rule = gate.snap.rule;
  const coolingLabel = (kind: string | null) => {
    if (kind === "reduction") return `减仓后 ${rule.cooling_reduction_days} 个交易日`;
    if (kind === "full_exit") return `清仓后 ${rule.cooling_exit_days} 个交易日`;
    if (kind === "fundamental") return `证伪后至少 ${rule.cooling_exit_days} 个交易日`;
    return kind || "";
  };
  const [amount, setAmount] = useState("20000");
  const [saving, setSaving] = useState(false);

  async function reenter(planId: number) {
    setSaving(true);
    try {
      await api(`/api/plans/${planId}/reentry`, {
        method: "POST",
        body: JSON.stringify({
          w_approved: Number(amount),
          industry_ok: true,
          fundamental_ok: true,
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
      {rows.length === 0 ? <div className="card">当前没有冷静期。第一次减仓后禁买 {rule.cooling_reduction_days} 个交易日，清仓后 {rule.cooling_exit_days} 个交易日。</div> : null}
      {rows.map((plan) => (
        <section key={plan.id} className="card stack">
          <h2>{plan.code} {plan.name}</h2>
          <p>{plan.view.cooling_active ? "冷静期进行中" : "冷静期已结束"} · {coolingLabel(plan.view.cooling_kind)}</p>
          <p className="hint">自 {plan.view.cooling_start} 至 {plan.view.cooling_until}（含当日）不能买。前次破位位 {px(plan.view.breakdown)}。{plan.view.p0_cancelled ? `相对 P0 下跌 ${((1 - rule.p0_cancel) * 100).toFixed(0)}% 的这一轮不能恢复。` : ""}</p>
          {plan.fundamental_veto ? <p className="hint">重大否决：{plan.veto_note}。价格上涨本身不能作为恢复理由。</p> : null}
          {!plan.view.cooling_active && !plan.view.p0_cancelled && !plan.fundamental_veto ? (
            <div className="row">
              <label>重新准入金额<input value={amount} onChange={(event) => setAmount(event.target.value)} /></label>
              <button className="btn" disabled={saving} onClick={() => reenter(plan.id)}>提交重新准入</button>
            </div>
          ) : null}
        </section>
      ))}
    </div>
  );
}
