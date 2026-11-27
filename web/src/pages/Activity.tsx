import { useEffect, useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";

type Item = {
  id: number;
  at: string;
  actor_name: string;
  owner_id: string;
  owner_name: string;
  action: string;
  subject: string;
  code: string;
  name: string;
  summary: string;
  fill_id: number | null;
};

const OPERATIONS = ["记入", "修改", "撤回"];
const SUBJECTS = ["买入单只股票", "卖出单只股票", "修改单只股票", "出资", "撤资"];

export function ActivityPage({ gate }: { gate: Gate }) {
  const [items, setItems] = useState<Item[]>([]);
  const [admin, setAdmin] = useState(gate.admin);
  const [busy, setBusy] = useState<number | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [actor, setActor] = useState("");
  const [action, setAction] = useState("");
  const [subject, setSubject] = useState("");

  async function load() {
    const data = await api<{ admin: boolean; items: Item[] }>("/api/activity");
    setAdmin(data.admin);
    setItems(data.items);
  }

  useEffect(() => {
    load().catch((error) => gate.report(error));
  }, [gate.snap.as_of]);

  async function withdraw(item: Item) {
    if (item.fill_id == null) return;
    if (!window.confirm(`撤回 ${item.code} 的这笔成交？`)) return;
    setBusy(item.id);
    try {
      const query = item.owner_id && item.owner_id !== "" ? `?owner_id=${encodeURIComponent(item.owner_id)}` : "";
      await api(`/api/positions/fills/${item.fill_id}/withdraw${query}`, { method: "POST" });
      gate.report("");
      await gate.reload();
      await load();
    } catch (error) {
      gate.report(error);
    } finally {
      setBusy(null);
    }
  }

  const actors = [...new Set(items.map((item) => item.actor_name).filter(Boolean))].sort();
  const actions = [...new Set([...OPERATIONS, ...items.map((item) => item.action).filter(Boolean)])];
  const subjects = [...new Set([...SUBJECTS, ...items.map((item) => item.subject).filter(Boolean)])];
  const shown = items.filter((item) => {
    const day = item.at.slice(0, 10);
    if (from && day < from) return false;
    if (to && day > to) return false;
    if (actor && item.actor_name !== actor) return false;
    if (action && item.action !== action) return false;
    if (subject && item.subject !== subject) return false;
    return true;
  });

  return (
    <section className="card">
      <h2>操作记录</h2>
      <p className="hint">
        {admin ? "你是管理员，这里是所有人的记录。其他人只能看到并操作自己的。" : "这里只显示你自己的记录。"}
        操作是记入、修改或撤回。对象是买入或卖出单只股票，以及出资、撤资。
      </p>
      <div className="filters">
        <label>从<input type="date" value={from} onChange={(event) => setFrom(event.target.value)} /></label>
        <label>到<input type="date" value={to} onChange={(event) => setTo(event.target.value)} /></label>
        <label>操作人
          <select value={actor} onChange={(event) => setActor(event.target.value)}>
            <option value="">全部</option>
            {actors.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
        <label>操作
          <select value={action} onChange={(event) => setAction(event.target.value)}>
            <option value="">全部</option>
            {actions.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
        <label>对象
          <select value={subject} onChange={(event) => setSubject(event.target.value)}>
            <option value="">全部</option>
            {subjects.map((name) => <option key={name} value={name}>{name}</option>)}
          </select>
        </label>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th><th>操作人</th>{admin ? <th>账本</th> : null}<th>操作</th><th>对象</th><th>说明</th><th></th>
            </tr>
          </thead>
          <tbody>
            {shown.map((item) => (
              <tr key={`${item.owner_id}-${item.id}`}>
                <td>{item.at.replace("T", " ").slice(0, 19)}</td>
                <td>{item.actor_name}</td>
                {admin ? <td>{item.owner_name}</td> : null}
                <td>{item.action}</td>
                <td>{item.subject}</td>
                <td>{item.code} {item.name} · {item.summary}</td>
                <td>
                  {item.fill_id != null ? (
                    <button className="btn secondary" type="button" disabled={busy === item.id} onClick={() => withdraw(item)}>撤回</button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length === 0 ? <p className="hint">还没有操作。</p> : shown.length === 0 ? <p className="hint">没有符合条件的记录。</p> : null}
    </section>
  );
}
