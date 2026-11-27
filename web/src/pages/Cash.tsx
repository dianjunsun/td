import { useEffect, useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { money } from "../format";

type Person = { id: string; username: string; admin: boolean };

type Flow = {
  id: number;
  kind: "in" | "out";
  kind_label: string;
  contributor: string;
  occurred_at: string;
  amount: number;
  note: string;
};

type Contributor = {
  name: string;
  contributed: number;
  withdrawn: number;
  net: number;
  last_at: string;
};

type Book = {
  cash: number;
  contributed: number;
  withdrawn: number;
  net: number;
  trade_cash: number;
  opening: number;
  contributors: Contributor[];
  flows: Flow[];
};

function nowLocal(): string {
  const day = new Date();
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${day.getFullYear()}-${pad(day.getMonth() + 1)}-${pad(day.getDate())}T${pad(day.getHours())}:${pad(day.getMinutes())}`;
}

function stamp(value: string): string {
  return value.replace("T", " ").slice(0, 16);
}

export function CashPage({ gate }: { gate: Gate }) {
  const [owner, setOwner] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [book, setBook] = useState<Book | null>(null);
  const [editing, setEditing] = useState<Flow | null>(null);
  const [contributor, setContributor] = useState("");
  const [occurredAt, setOccurredAt] = useState(nowLocal);
  const [kind, setKind] = useState<"in" | "out">("in");
  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [busy, setBusy] = useState<number | null>(null);

  async function load(nextOwner = owner) {
    const query = nextOwner ? `?owner_id=${encodeURIComponent(nextOwner)}` : "";
    const data = await api<Book>(`/api/capital${query}`);
    setBook(data);
  }

  useEffect(() => {
    if (!gate.admin) return;
    api<Person[]>("/api/users").then(setPeople).catch((error) => gate.report(error));
  }, [gate.admin]);

  useEffect(() => {
    load().catch((error) => gate.report(error));
  }, [owner, gate.snap.account.cash]);

  function fill(flow: Flow | null) {
    setEditing(flow);
    setContributor(flow?.contributor || "");
    setOccurredAt(flow ? flow.occurred_at.slice(0, 16) : nowLocal());
    setKind(flow?.kind || "in");
    setAmount(flow ? String(flow.amount) : "");
    setNote(flow?.note || "");
  }

  async function save() {
    const next = Number(amount);
    if (!contributor.trim() || !occurredAt || amount.trim() === "" || Number.isNaN(next) || next <= 0) {
      gate.report(new Error("出资人、时间和金额都要填，金额要大于 0。"));
      return;
    }
    setSaving(true);
    try {
      const payload = {
        contributor: contributor.trim(),
        occurred_at: occurredAt,
        kind,
        amount: next,
        note: note.trim(),
        owner_id: owner,
      };
      const path = editing ? `/api/capital/${editing.id}` : "/api/capital";
      const data = await api<Book>(path, { method: editing ? "PATCH" : "POST", body: JSON.stringify(payload) });
      setBook(data);
      gate.report("");
      if (!owner) await gate.reload();
      fill(null);
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  async function withdraw(flow: Flow) {
    if (!window.confirm(`撤回 ${flow.contributor} 的这笔${flow.kind_label}？`)) return;
    setBusy(flow.id);
    try {
      const query = owner ? `?owner_id=${encodeURIComponent(owner)}` : "";
      const data = await api<Book>(`/api/capital/${flow.id}/withdraw${query}`, { method: "POST" });
      setBook(data);
      if (editing?.id === flow.id) fill(null);
      gate.report("");
      if (!owner) await gate.reload();
    } catch (error) {
      gate.report(error);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="card">
      <div className="top">
        <h2>现金</h2>
        {gate.admin ? (
          <label className="asof">账本
            <select value={owner} onChange={(event) => { setOwner(event.target.value); fill(null); }}>
              <option value="">我的</option>
              {people.filter((item) => item.username).map((item) => (
                <option key={item.id} value={item.id}>{item.username}</option>
              ))}
            </select>
          </label>
        ) : null}
      </div>
      <p className="hint">当前现金等于期初现金、净出资和买卖净额。仓位页的总资产等于这里的现金加上持仓市值。</p>
      <div className="summary">
        <div><div className="hint">当前现金</div><div className="stat">{money(book?.cash)}</div></div>
        <div><div className="hint">期初现金</div><div className="stat">{money(book?.opening)}</div><div className="hint">记出资之前已在账上</div></div>
        <div><div className="hint">累计出资</div><div className="stat">{money(book?.contributed)}</div></div>
        <div><div className="hint">累计撤资</div><div className="stat">{money(book?.withdrawn)}</div></div>
        <div><div className="hint">净出资</div><div className="stat">{money(book?.net)}</div></div>
        <div><div className="hint">买卖净额</div><div className="stat">{money(book?.trade_cash)}</div><div className="hint">卖出减去买入</div></div>
      </div>

      <h3>{editing ? "修改这笔" : "记一笔"}</h3>
      <div className="grid">
        <label>出资人
          <input value={contributor} onChange={(event) => setContributor(event.target.value)} placeholder="姓名" />
        </label>
        <label>时间
          <input type="datetime-local" value={occurredAt} onChange={(event) => setOccurredAt(event.target.value)} />
        </label>
        <label>方向
          <select value={kind} onChange={(event) => setKind(event.target.value as "in" | "out")}>
            <option value="in">出资</option>
            <option value="out">撤资</option>
          </select>
        </label>
        <label>金额
          <input value={amount} inputMode="decimal" onChange={(event) => setAmount(event.target.value)} placeholder="0.00" />
        </label>
        <label className="span-2">备注
          <input value={note} onChange={(event) => setNote(event.target.value)} placeholder="可选" />
        </label>
      </div>
      <div className="row">
        <button className="btn" type="button" disabled={saving} onClick={save}>{saving ? "保存中…" : editing ? "保存修改" : "记入"}</button>
        {editing ? <button className="btn secondary" type="button" onClick={() => fill(null)}>取消</button> : null}
      </div>

      <h3>出资人</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>出资人</th><th className="num">出资</th><th className="num">撤资</th><th className="num">净额</th><th>最近时间</th></tr>
          </thead>
          <tbody>
            {(book?.contributors || []).map((item) => (
              <tr key={item.name}>
                <td>{item.name}</td>
                <td className="num">{money(item.contributed)}</td>
                <td className="num">{money(item.withdrawn)}</td>
                <td className="num">{money(item.net)}</td>
                <td>{stamp(item.last_at)}</td>
              </tr>
            ))}
            {book && book.contributors.length === 0 ? <tr><td colSpan={5}>还没有出资记录。</td></tr> : null}
          </tbody>
        </table>
      </div>

      <h3>明细</h3>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th>时间</th><th>出资人</th><th>方向</th><th className="num">金额</th><th>备注</th><th></th></tr>
          </thead>
          <tbody>
            {(book?.flows || []).map((flow) => (
              <tr key={flow.id}>
                <td>{stamp(flow.occurred_at)}</td>
                <td>{flow.contributor}</td>
                <td>{flow.kind_label}</td>
                <td className="num">{money(flow.amount)}</td>
                <td>{flow.note || "—"}</td>
                <td>
                  <div className="row">
                    <button className="btn secondary" type="button" onClick={() => fill(flow)}>修改</button>
                    <button className="btn secondary" type="button" disabled={busy === flow.id} onClick={() => withdraw(flow)}>撤回</button>
                  </div>
                </td>
              </tr>
            ))}
            {book && book.flows.length === 0 ? <tr><td colSpan={6}>还没有明细。</td></tr> : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}
