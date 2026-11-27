import { useEffect, useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { ASSETS, money, pct, px, shares } from "../format";
import type { Fill, Listing, Plan, RuleParams, Snapshot } from "../types";

const REFRESH = [3000, 5000, 15000, 30000, 60000, 0] as const;
const NAME_CACHE = "td-symbol-names";

type Live = {
  price: number | null;
  value: number | null;
  pnl: number | null;
  swing: number | null;
  drawdown: number | null;
};

type Person = { id: string; username: string; admin: boolean };

export function PositionsPage({ gate }: { gate: Gate }) {
  const [owner, setOwner] = useState("");
  const [people, setPeople] = useState<Person[]>([]);
  const [foreign, setForeign] = useState<Snapshot | null>(null);
  const snap = owner ? foreign : gate.snap;
  const plans = [...(snap?.plans || [])].sort((a, b) => Number(b.view.shares > 0) - Number(a.view.shares > 0));
  const [selected, setSelected] = useState<number | "book" | "new">(gate.draft ? "new" : "book");
  const [live, setLive] = useState<Record<string, number>>({});
  const [refreshedAt, setRefreshedAt] = useState("");
  const [pulling, setPulling] = useState(false);
  const [refreshMs, setRefreshMs] = useState(storedRefresh);
  const plan = typeof selected === "number" ? plans.find((item) => item.id === selected) || null : null;

  useEffect(() => {
    if (gate.draft) setSelected("new");
  }, [gate.draft]);

  useEffect(() => {
    if (!gate.admin) return;
    api<Person[]>("/api/users").then(setPeople).catch((error) => gate.report(error));
  }, [gate.admin]);

  useEffect(() => {
    if (!owner) {
      setForeign(null);
      return;
    }
    api<Snapshot>(`/api/snapshot?as_of=${gate.asOf}&user_id=${encodeURIComponent(owner)}`)
      .then(setForeign)
      .catch((error) => gate.report(error));
  }, [owner, gate.asOf, gate.snap]);

  const heldCodes = [...new Set(plans.filter((item) => /^\d{6}$/.test(item.code)).map((item) => item.code))].join(",");
  async function fetchQuotes() {
    const codes = heldCodes ? heldCodes.split(",").filter(Boolean) : [];
    if (!codes.length || !gate.quoteSource) throw new Error("没有可以按行情更新的股票");
    const quotes = await api<Listing[]>("/api/market/quotes", {
      method: "POST",
      body: JSON.stringify({ source: gate.quoteSource, codes }),
    });
    const next: Record<string, number> = {};
    quotes.forEach((item) => {
      if (item.price != null) next[item.code] = item.price;
    });
    setLive(next);
    setRefreshedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
  }
  useEffect(() => {
    const codes = heldCodes ? heldCodes.split(",").filter(Boolean) : [];
    if (!codes.length || !gate.quoteSource) return;
    let stopped = false;
    async function pull() {
      if (document.hidden || stopped) return;
      try {
        await fetchQuotes();
      } catch {
        /* 行情暂时没有时保留上一轮价格 */
      }
    }
    pull();
    if (!refreshMs) return () => { stopped = true; };
    const timer = window.setInterval(pull, refreshMs);
    const onVisible = () => { if (!document.hidden) pull(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [heldCodes, gate.quoteSource, refreshMs]);

  async function reload(day?: string) {
    if (!owner) {
      await gate.reload(day);
      return;
    }
    const data = await api<Snapshot>(`/api/snapshot?as_of=${day || gate.asOf}&user_id=${encodeURIComponent(owner)}`);
    setForeign(data);
  }

  function chooseRefresh(next: number) {
    localStorage.setItem("td-refresh-ms", String(next));
    setRefreshMs(next);
  }

  async function updateNow() {
    setPulling(true);
    try {
      await fetchQuotes();
      gate.report("");
    } catch (error) {
      gate.report(error);
    } finally {
      setPulling(false);
    }
  }

  const sourceLabel = gate.quoteSources.find((item) => item.id === gate.quoteSource)?.label || "";
  const params = snap?.rule.params ?? gate.snap.rule.params;
  const open = plans.filter((item) => item.view.shares > 0);
  const rows = open.map((item) => ({ plan: item, live: liveOf(item, live[item.code], params.anchor_multiple) }));
  const totalValue = rows.reduce((sum, item) => sum + (item.live.value || 0), 0);
  const totalPnl = rows.reduce((sum, item) => sum + (item.live.pnl || 0), 0);
  const totalPct = rate(totalPnl, costOf(rows));

  return (
    <div className="book">
      <section className="card picks">
        {gate.admin ? (
          <label>账本
            <select value={owner} onChange={(event) => { setOwner(event.target.value); setSelected("book"); }}>
              <option value="">我的</option>
              {people.filter((item) => item.username).map((item) => (
                <option key={item.id} value={item.id}>{item.username}</option>
              ))}
            </select>
          </label>
        ) : null}
        <div className="pick-list">
        <button className={`pick ${selected === "book" ? "active" : ""}`} onClick={() => setSelected("book")}>
          <span className="pick-head"><strong>总仓位</strong></span>
          <span className="pick-facts">
            <span><span>持仓</span><b>{open.length} 只</b></span>
            <span><span>市值</span><b>{money(totalValue)}</b></span>
            <span><span>盈亏</span><b className={tone(totalPnl)}>{money(totalPnl)}</b></span>
            <span><span>盈亏比例</span><b className={tone(totalPct)}>{pct(totalPct)}</b></span>
          </span>
        </button>
        <button className={`pick ${selected === "new" ? "active" : ""}`} onClick={() => setSelected("new")}>记新仓位</button>
        {plans.map((item) => {
          const stats = liveOf(item, live[item.code], params.anchor_multiple);
          return (
            <button key={item.id} className={`pick ${plan?.id === item.id ? "active" : ""}`} onClick={() => setSelected(item.id)}>
              <span className="pick-head">
                <strong>{item.code}</strong>
                <span>{item.name}</span>
              </span>
              <span className="pick-facts">
                <span><span>股数</span><b>{shares(item.view.shares)}</b></span>
                <span><span>成本</span><b>{px(item.view.c)}</b></span>
                <span><span>现价</span><b>{px(stats.price)}</b></span>
                <span><span>市值</span><b>{money(stats.value)}</b></span>
                <span><span>相对成本</span><b className={tone(stats.swing)}>{pct(stats.swing)}</b></span>
                <span><span>盈亏</span><b className={tone(stats.pnl)}>{money(stats.pnl)}</b></span>
                <span><span>回撤</span><b className={tone(stats.drawdown)}>{pct(stats.drawdown)}</b></span>
              </span>
            </button>
          );
        })}
        </div>
      </section>
      {selected === "book" ? (
        <Cockpit rows={rows} account={snap?.account ?? null} params={params} refreshMs={refreshMs} refreshedAt={refreshedAt} source={sourceLabel} pulling={pulling} onRefresh={chooseRefresh} onUpdate={updateNow} onOpenCash={() => gate.go("cash")} onOpen={(id) => setSelected(id)} />
      ) : (
        <PositionForm
          key={`${owner}-${plan?.id ?? "new"}-${gate.draft?.code || ""}`}
          gate={gate}
          plan={selected === "new" ? null : plan}
          owner={owner}
          reload={reload}
          quotePrice={plan ? live[plan.code] : undefined}
          refreshMs={refreshMs}
          refreshedAt={refreshedAt}
          source={sourceLabel}
          onRefresh={chooseRefresh}
        />
      )}
    </div>
  );
}

type Row = { plan: Plan; live: Live };
type SortKey = "value" | "pnl" | "swing" | "drawdown" | "shares" | "cost" | "price";

function Cockpit({ rows, account, params, refreshMs, refreshedAt, source, pulling, onRefresh, onUpdate, onOpenCash, onOpen }: {
  rows: Row[];
  account: Snapshot["account"] | null;
  params: RuleParams;
  refreshMs: number;
  refreshedAt: string;
  source: string;
  pulling: boolean;
  onRefresh: (next: number) => void;
  onUpdate: () => void;
  onOpenCash: () => void;
  onOpen: (id: number) => void;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("value");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const value = rows.reduce((sum, item) => sum + (item.live.value || 0), 0);
  const pnl = rows.reduce((sum, item) => sum + (item.live.pnl || 0), 0);
  const cost = costOf(rows);
  const pnlPct = rate(pnl, cost);
  const cash = account?.cash ?? 0;
  const assets = cash + value;
  const base = assets > 0 ? assets : 0;
  const baseLabel = "占总资产";
  const sorted = [...rows].sort((a, b) => compareRow(a, b, sortKey, sortDir));
  const types = groupRows(rows, (plan) => plan.asset_type, (plan) => plan.asset_label, (plan) => params.asset_caps[plan.asset_type] ?? plan.asset_cap);
  const industries = groupRows(rows, (plan) => plan.industry, (plan) => plan.industry, () => params.industry_cap);
  const themes = groupRows(rows, (plan) => plan.theme, (plan) => plan.theme, () => params.industry_cap);
  const high = rows.filter((item) => item.plan.high_vol);
  function toggle(key: SortKey) {
    if (sortKey === key) setSortDir((dir) => dir === "desc" ? "asc" : "desc");
    else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  return (
    <section className="card">
      <div className="top">
        <h2>总仓位</h2>
        <div className="refresh-bar">
          <RefreshControl refreshMs={refreshMs} onRefresh={onRefresh} />
          <button className="btn secondary" type="button" disabled={pulling} onClick={onUpdate}>{pulling ? "更新中…" : "立即更新"}</button>
        </div>
      </div>
      <h3>资金盘</h3>
      <p className="hint">总资产按当前现金加上持仓市值计算。现金在现金页按出资人和时间管理。</p>
      <div className="summary">
        <div><div className="hint">总资产</div><div className="stat">{money(assets)}</div><div className="hint">现金 + 持仓市值</div></div>
        <div>
          <div className="hint">现金</div>
          <div className="stat">{money(cash)}</div>
          <button className="btn secondary" type="button" onClick={onOpenCash}>管理现金</button>
        </div>
        <div><div className="hint">持仓市值</div><div className="stat">{money(value)}</div><div className="hint">{rows.length} 只</div></div>
        <div><div className="hint">仓位</div><div className="stat">{pct(base > 0 ? value / base : null)}</div><div className="hint">上限 {pct(account?.regime_cap)}</div></div>
        <div><div className="hint">浮动盈亏</div><div className={`stat ${tone(pnl)}`}>{money(pnl)}</div></div>
        <div><div className="hint">盈亏比例</div><div className={`stat ${tone(pnlPct)}`}>{pct(pnlPct)}</div><div className="hint">相对持仓成本 {money(cost)}</div></div>
      </div>
      <h3>分类仓位</h3>
      <GroupTable title="股票类型" rows={types} base={base} baseLabel={baseLabel} />
      <GroupTable title="行业" rows={industries} base={base} baseLabel={baseLabel} />
      <GroupTable title="主题" rows={themes} base={base} baseLabel={baseLabel} />
      {high.length ? (
        <p className="hint">
          高波动合计 {money(high.reduce((sum, item) => sum + (item.live.value || 0), 0))}
          ，{baseLabel} {pct(base > 0 ? high.reduce((sum, item) => sum + (item.live.value || 0), 0) / base : null)}
          ，上限 {pct(params.high_vol_group_cap)}。
        </p>
      ) : null}
      <p className="hint">{refreshText(refreshMs, source, refreshedAt)}点进某一只，才看每一笔成交。</p>
      <div className="table-wrap">
        <table className="board">
          <thead>
            <tr>
              <th>股票</th>
              <SortHead label="股数" k="shares" sortKey={sortKey} sortDir={sortDir} onSort={toggle} />
              <SortHead label="成本" k="cost" sortKey={sortKey} sortDir={sortDir} onSort={toggle} />
              <SortHead label="现价" k="price" sortKey={sortKey} sortDir={sortDir} onSort={toggle} />
              <SortHead label="盈亏比例" k="swing" sortKey={sortKey} sortDir={sortDir} onSort={toggle} />
              <SortHead label="盈亏" k="pnl" sortKey={sortKey} sortDir={sortDir} onSort={toggle} />
              <SortHead label="持有市值" k="value" sortKey={sortKey} sortDir={sortDir} onSort={toggle} />
              <SortHead label="回撤" k="drawdown" sortKey={sortKey} sortDir={sortDir} onSort={toggle} />
            </tr>
          </thead>
          <tbody>
            {sorted.map(({ plan, live: stats }) => (
              <tr key={plan.id} onClick={() => onOpen(plan.id)}>
                <td>{plan.name}<div className="hint">{plan.code} · {plan.asset_label}</div></td>
                <td className="num">{shares(plan.view.shares)}</td>
                <td className="num">{px(plan.view.c)}</td>
                <td className="num">{px(stats.price)}</td>
                <td className={`num ${tone(stats.swing)}`}>{pct(stats.swing)}</td>
                <td className={`num ${tone(stats.pnl)}`}>{money(stats.pnl)}</td>
                <td className="num">{money(stats.value)}</td>
                <td className={`num ${tone(stats.drawdown)}`}>{pct(stats.drawdown)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 ? <p className="hint">还没有持仓。</p> : null}
    </section>
  );
}

function SortHead({ label, k, sortKey, sortDir, onSort }: {
  label: string;
  k: SortKey;
  sortKey: SortKey;
  sortDir: "desc" | "asc";
  onSort: (key: SortKey) => void;
}) {
  const active = sortKey === k;
  return (
    <th className={`num sort${active ? " active" : ""}`} aria-sort={active ? (sortDir === "desc" ? "descending" : "ascending") : "none"}>
      <button type="button" className="sort-btn" onClick={() => onSort(k)}>
        {label}
        <span className="carets" aria-hidden="true">
          <i className={active && sortDir === "asc" ? "up on" : "up"} />
          <i className={active && sortDir === "desc" ? "down on" : "down"} />
        </span>
      </button>
    </th>
  );
}

function GroupTable({ title, rows, base, baseLabel }: {
  title: string;
  rows: Group[];
  base: number;
  baseLabel: string;
}) {
  if (!rows.length) return null;
  return (
    <div className="groups">
      <div className="hint">{title}</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>分类</th><th className="num">市值</th><th className="num">{baseLabel}</th><th className="num">上限</th>
              <th className="num">盈亏</th><th className="num">盈亏比例</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const weight = base > 0 ? row.value / base : null;
              const over = weight != null && row.cap > 0 && weight > row.cap;
              return (
                <tr key={row.key}>
                  <td>{row.label}</td>
                  <td className="num">{money(row.value)}</td>
                  <td className="num">
                    {pct(weight)}
                    {row.cap > 0 && weight != null ? <div className="bar"><span style={{ width: `${Math.min(100, (weight / row.cap) * 100)}%` }} /></div> : null}
                    {over ? <div className="hint">超过上限</div> : null}
                  </td>
                  <td className="num">{pct(row.cap)}</td>
                  <td className={`num ${tone(row.pnl)}`}>{money(row.pnl)}</td>
                  <td className={`num ${tone(rate(row.pnl, row.cost))}`}>{pct(rate(row.pnl, row.cost))}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

type Group = { key: string; label: string; value: number; pnl: number; cost: number; cap: number };

function groupRows(rows: Row[], keyOf: (plan: Plan) => string, labelOf: (plan: Plan) => string, capOf: (plan: Plan) => number): Group[] {
  const map = new Map<string, Group>();
  rows.forEach((row) => {
    const key = (keyOf(row.plan) || "").trim();
    if (!key) return;
    const item = map.get(key) || { key, label: labelOf(row.plan), value: 0, pnl: 0, cost: 0, cap: capOf(row.plan) || 0 };
    item.value += row.live.value || 0;
    item.pnl += row.live.pnl || 0;
    item.cost += row.plan.view.c == null ? 0 : row.plan.view.c * row.plan.view.shares;
    map.set(key, item);
  });
  return [...map.values()].sort((a, b) => b.value - a.value);
}

function costOf(rows: Row[]) {
  return rows.reduce((sum, item) => sum + (item.plan.view.c == null ? 0 : item.plan.view.c * item.plan.view.shares), 0);
}

function rate(pnl: number, cost: number) {
  return cost > 0 ? pnl / cost : null;
}

function compareRow(a: Row, b: Row, key: SortKey, dir: "desc" | "asc") {
  const left = sortValue(a, key);
  const right = sortValue(b, key);
  if (left == null && right == null) return 0;
  if (left == null) return 1;
  if (right == null) return -1;
  return dir === "desc" ? right - left : left - right;
}

function sortValue(row: Row, key: SortKey) {
  if (key === "shares") return row.plan.view.shares;
  if (key === "cost") return row.plan.view.c;
  if (key === "price") return row.live.price;
  return row.live[key];
}

function PositionForm({ gate, plan, owner, reload, quotePrice, refreshMs, refreshedAt, source, onRefresh }: {
  gate: Gate;
  plan: Plan | null;
  owner: string;
  reload: (day?: string) => Promise<void>;
  quotePrice?: number;
  refreshMs: number;
  refreshedAt: string;
  source: string;
  onRefresh: (next: number) => void;
}) {
  const [code, setCode] = useState(plan?.code || gate.draft?.code || "");
  const [asset, setAsset] = useState(plan?.asset_type || "large_cap");
  const [side, setSide] = useState("buy");
  const [day, setDay] = useState(gate.asOf);
  const [price, setPrice] = useState("");
  const [qty, setQty] = useState("");
  const [saving, setSaving] = useState(false);
  const [edit, setEdit] = useState<Fill | null>(null);
  const symbol = useSymbol(plan ? "" : code, gate.quoteSource, gate.draft?.name || "");
  const name = plan?.name || symbol.name;
  const view = plan?.view;
  const stats = plan ? liveOf(plan, quotePrice, gate.snap.rule.params.anchor_multiple) : null;
  const params = gate.snap.rule.params;
  const pause = view?.c == null ? null : view.c * params.p0_pause;
  const cancel = view?.c == null ? null : view.c * params.p0_cancel;

  useEffect(() => {
    if (gate.draft && !plan) gate.setDraft(null);
  }, [gate.draft]);

  async function send(action: "trade" | "price" | "type", extra: { price?: number; shares?: number; asset_type?: string } = {}) {
    setSaving(true);
    try {
      await api("/api/positions", {
        method: "POST",
        body: JSON.stringify({
          code: code.trim(),
          name,
          asset_type: extra.asset_type || asset,
          action,
          side,
          trade_date: day,
          price: extra.price,
          shares: extra.shares,
          source: gate.quoteSource,
          owner_id: owner,
        }),
      });
      gate.report("");
      await reload(day);
      if (action === "trade") {
        setPrice("");
        setQty("");
      }
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  async function saveEdit() {
    if (!edit) return;
    setSaving(true);
    try {
      await api(`/api/positions/fills/${edit.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          side: edit.side,
          trade_date: edit.trade_date,
          price: Number(edit.price),
          shares: Number(edit.shares),
          owner_id: owner,
        }),
      });
      setEdit(null);
      gate.report("");
      await reload(edit.trade_date);
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  async function withdraw(fill: Fill) {
    if (!window.confirm(`撤回 ${fill.trade_date} 的${fill.side === "buy" ? "买入" : "卖出"}？`)) return;
    setSaving(true);
    try {
      const query = owner ? `?owner_id=${encodeURIComponent(owner)}` : "";
      await api(`/api/positions/fills/${fill.id}/withdraw${query}`, { method: "POST" });
      gate.report("");
      await reload();
    } catch (error) {
      gate.report(error);
    } finally {
      setSaving(false);
    }
  }

  const ready = Boolean(plan) || symbol.state === "ready";

  return (
    <div className="section">
      {view && stats ? (
        <section className="card">
          <div className="symbol-bar">
            <h2 className="symbol-title"><strong>{plan?.code}</strong><span>{plan?.name}</span></h2>
            <RefreshControl refreshMs={refreshMs} onRefresh={onRefresh} />
          </div>
          <div className="metrics">
            <div><div className="hint">股票类型</div><div className="stat">{plan?.asset_label}</div></div>
            <div><div className="hint">持仓数量</div><div className="stat">{shares(view.shares)}</div></div>
            <div><div className="hint">建仓成本</div><div className="stat">{px(view.c)}</div></div>
            <div><div className="hint">现价</div><div className="stat">{px(stats.price)}</div></div>
            <div><div className="hint">相对成本</div><div className={`stat ${tone(stats.swing)}`}>{pct(stats.swing)}</div></div>
            <div><div className="hint">回撤</div><div className={`stat ${tone(stats.drawdown)}`}>{pct(stats.drawdown)}</div></div>
            <div><div className="hint">盈亏</div><div className={`stat ${tone(stats.pnl)}`}>{money(stats.pnl)}</div></div>
            <div><div className="hint">市值</div><div className="stat">{money(stats.value)}</div></div>
          </div>
          <p className="hint">
            {plan && /^\d{6}$/.test(plan.code) ? refreshText(refreshMs, source, refreshedAt) : "这只没有行情代码，现价用上次记下的价格。"}
            {plan && /^\d{6}$/.test(plan.code) && quotePrice == null && view.last_price != null ? "这轮还没取到，暂时用上次记下的价格。" : ""}
            容受波动：成本下跌到 {px(pause)} 仍可持有，到 {px(cancel)} 视为超出。
            回撤从{view.h != null && stats.price != null && stats.price >= (view.h || 0) && view.c != null && stats.price >= view.c * params.anchor_multiple ? "最高价" : view.r === view.h ? "最高价" : "成本"}算。
          </p>
        </section>
      ) : null}

      <section className="card stack">
        <h2>{plan ? "记一笔" : "新仓位"}</h2>
        <div className="grid">
          <label>代码
            <input value={code} disabled={plan != null} placeholder="6 位代码，例如 600519" onChange={(event) => setCode(event.target.value)} />
          </label>
          <div>
            <div className="hint">名称</div>
            <div className="stat">{name || (symbol.state === "loading" ? "正在匹配…" : symbol.state === "missing" ? "行情里没有这只" : "—")}</div>
          </div>
          <label>股票类型
            <select value={asset} onChange={(event) => {
              const next = event.target.value;
              setAsset(next);
              if (plan) send("type", { asset_type: next });
            }}>
              {ASSETS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          <label>日期<input type="date" value={day} onChange={(event) => setDay(event.target.value)} /></label>
          <label>方向
            <select value={side} onChange={(event) => setSide(event.target.value)}>
              <option value="buy">买入</option>
              <option value="sell" disabled={!plan}>卖出</option>
            </select>
          </label>
          <label>价格<input value={price} onChange={(event) => setPrice(event.target.value)} /></label>
          <label>数量<input value={qty} onChange={(event) => setQty(event.target.value)} /></label>
        </div>
        <div className="row">
          <button className="btn secondary" type="button" onClick={async () => {
            if (!code.trim()) return;
            try {
              const quote = await api<{ price: string }>(`/api/quotes/${encodeURIComponent(code.trim())}?source=${encodeURIComponent(gate.quoteSource)}`);
              setPrice(quote.price);
              gate.report("");
            } catch (error) {
              gate.report(error);
            }
          }}>用行情填价格</button>
          <button className="btn" disabled={saving || !ready || !price || !qty} onClick={() => send("trade", { price: Number(price), shares: Number(qty) })}>记录成交</button>
          {plan ? <button className="btn secondary" disabled={saving || !price} onClick={() => send("price", { price: Number(price) })}>只更新现价</button> : null}
        </div>
        <p className="hint">名称由代码向行情匹配，代码是唯一键。成本按买入金额加权。记录可以修改或撤回。</p>
      </section>

      {plan ? (
        <section className="card">
          <h2>成交</h2>
          <div className="table-wrap">
            <table>
              <thead><tr><th>日期</th><th>方向</th><th className="num">价格</th><th className="num">数量</th><th className="num">金额</th><th></th></tr></thead>
              <tbody>
                {plan.fills.map((fill) => edit?.id === fill.id ? (
                  <tr key={fill.id}>
                    <td><input type="date" value={edit.trade_date} onChange={(event) => setEdit({ ...edit, trade_date: event.target.value })} /></td>
                    <td>
                      <select value={edit.side} onChange={(event) => setEdit({ ...edit, side: event.target.value })}>
                        <option value="buy">买入</option>
                        <option value="sell">卖出</option>
                      </select>
                    </td>
                    <td><input value={String(edit.price)} onChange={(event) => setEdit({ ...edit, price: Number(event.target.value) })} /></td>
                    <td><input value={String(edit.shares)} onChange={(event) => setEdit({ ...edit, shares: Number(event.target.value) })} /></td>
                    <td className="num">{money(Number(edit.price) * Number(edit.shares))}</td>
                    <td>
                      <button className="btn" type="button" disabled={saving} onClick={saveEdit}>保存</button>
                      <button className="btn secondary" type="button" onClick={() => setEdit(null)}>取消</button>
                    </td>
                  </tr>
                ) : (
                  <tr key={fill.id}>
                    <td>{fill.trade_date}</td>
                    <td className={fill.side === "buy" ? "rise" : "fall"}>{fill.side === "buy" ? "买入" : "卖出"}</td>
                    <td className="num">{px(fill.price)}</td>
                    <td className="num">{shares(fill.shares)}</td>
                    <td className="num">{money(fill.amount)}</td>
                    <td>
                      <button className="btn secondary" type="button" onClick={() => setEdit({ ...fill })}>修改</button>
                      <button className="btn secondary" type="button" disabled={saving} onClick={() => withdraw(fill)}>撤回</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {plan.fills.length === 0 ? <p className="hint">还没有成交。</p> : null}
        </section>
      ) : null}
    </div>
  );
}

function useSymbol(code: string, source: string, preset: string) {
  const [name, setName] = useState(preset);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "missing">(preset ? "ready" : "idle");

  useEffect(() => {
    const raw = code.trim();
    if (!raw) {
      setName("");
      setState("idle");
      return;
    }
    if (!/^\d{6}(\.(SH|SZ|BJ))?$/i.test(raw) && !/^(SH|SZ|BJ)\d{6}$/i.test(raw)) {
      setName("");
      setState("missing");
      return;
    }
    const cached = readNames()[raw.toUpperCase()];
    if (cached) {
      setName(cached);
      setState("ready");
    } else {
      setState("loading");
    }
    let stopped = false;
    const timer = window.setTimeout(() => {
      api<{ code: string; name: string }>(`/api/symbols/${encodeURIComponent(raw)}?source=${encodeURIComponent(source)}`)
        .then((item) => {
          if (stopped) return;
          writeName(item.code, item.name);
          setName(item.name);
          setState("ready");
        })
        .catch(() => {
          if (stopped || cached) return;
          setName("");
          setState("missing");
        });
    }, 300);
    return () => {
      stopped = true;
      window.clearTimeout(timer);
    };
  }, [code, source]);

  return { name, state };
}

function liveOf(plan: Plan, quote: number | undefined, anchorMultiple: number): Live {
  const cost = plan.view.c;
  const held = plan.view.shares;
  const price = quote ?? plan.view.last_price;
  const high = price == null ? plan.view.h : Math.max(plan.view.h ?? price, price);
  let anchor = plan.view.r ?? cost;
  if (cost != null && high != null && high >= cost * anchorMultiple) anchor = high;
  const drawdown = price != null && anchor ? price / anchor - 1 : null;
  const value = price != null ? held * price : null;
  const pnl = price != null && cost != null ? (price - cost) * held : null;
  const swing = price != null && cost ? price / cost - 1 : null;
  return { price, value, pnl, swing, drawdown };
}

function RefreshControl({ refreshMs, onRefresh }: { refreshMs: number; onRefresh: (next: number) => void }) {
  return (
    <label className="refresh">现价更新
      <select value={String(refreshMs)} onChange={(event) => onRefresh(Number(event.target.value))}>
        <option value="3000">每 3 秒</option>
        <option value="5000">每 5 秒</option>
        <option value="15000">每 15 秒</option>
        <option value="30000">每 30 秒</option>
        <option value="60000">每 60 秒</option>
        <option value="0">关闭</option>
      </select>
    </label>
  );
}

function refreshText(refreshMs: number, source: string, refreshedAt: string) {
  const clock = refreshedAt ? `上次 ${refreshedAt}。` : "";
  if (!refreshMs) return `自动更新已关闭。${clock}`;
  return `现价每 ${refreshMs / 1000} 秒向${source || "当前行情源"}更新。${clock}`;
}

function tone(value: number | null | undefined) {
  if (value == null || value === 0) return "";
  return value > 0 ? "rise" : "fall";
}

function storedRefresh() {
  const raw = localStorage.getItem("td-refresh-ms");
  const value = raw == null ? 3000 : Number(raw);
  return (REFRESH as readonly number[]).includes(value) ? value : 3000;
}

function readNames(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(NAME_CACHE) || "{}");
  } catch {
    return {};
  }
}

function writeName(code: string, name: string) {
  const all = readNames();
  all[code] = name;
  localStorage.setItem(NAME_CACHE, JSON.stringify(all));
}
