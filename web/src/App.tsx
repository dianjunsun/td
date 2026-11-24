import { useCallback, useEffect, useState } from "react";
import { ApiError, api, clearAuth, setAuth, storedUser } from "./api";
import { localISO } from "./format";
import { AccountPage } from "./pages/Account";
import { BookPage } from "./pages/Book";
import { CoolingPage } from "./pages/Cooling";
import { Dashboard } from "./pages/Dashboard";
import { MarketPage } from "./pages/Market";
import { PlansPage } from "./pages/Plans";
import { ReviewPage } from "./pages/Review";
import { RiskPage } from "./pages/Risk";
import { RulesPage } from "./pages/Rules";
import { TradePage } from "./pages/Trade";
import type { Handbook, QuoteSource, Snapshot } from "./types";

const TABS = [
  ["market", "看盘"],
  ["dashboard", "今日看板"],
  ["account", "市场闸门"],
  ["plans", "交易计划"],
  ["trade", "建仓与成交"],
  ["risk", "持仓与风险线"],
  ["cooling", "冷静期"],
  ["book", "组合暴露"],
  ["review", "复盘"],
  ["rules", "规则参数"],
] as const;

export type Gate = {
  asOf: string;
  setAsOf: (day: string) => void;
  snap: Snapshot;
  reload: (day?: string) => Promise<void>;
  report: (error: unknown) => void;
  selected: number | null;
  setSelected: (id: number) => void;
  go: (tab: string) => void;
  draft: { code: string; name: string } | null;
  setDraft: (draft: { code: string; name: string } | null) => void;
  quoteSources: QuoteSource[];
  quoteSource: string;
  setQuoteSource: (id: string) => void;
};

export function App() {
  const [user, setUser] = useState(storedUser);
  const [tab, setTab] = useState(() => location.hash.replace("#", "") || "market");
  const [draft, setDraft] = useState<{ code: string; name: string } | null>(null);
  const [asOf, setAsOf] = useState(localISO);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [handbook, setHandbook] = useState<Handbook | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [quoteSources, setQuoteSources] = useState<QuoteSource[]>([]);
  const [quoteSource, setQuoteSource] = useState(() => localStorage.getItem("td-quote-source") || "");

  const reload = useCallback(async (day?: string) => {
    const data = await api<Snapshot>(`/api/snapshot?as_of=${day || asOf}`);
    setSnap(data);
  }, [asOf]);

  function signOut(message = "") {
    clearAuth();
    setUser("");
    setSnap(null);
    setHandbook(null);
    setError(message);
  }

  useEffect(() => {
    if (!user) return;
    let alive = true;
    api<{ username: string }>("/api/auth/me")
      .then(() => reload())
      .catch((err) => {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          signOut("请先登录");
          return;
        }
        setError(err instanceof Error ? err.message : "加载失败");
      });
    api<Handbook>("/api/handbook").then((book) => {
      if (alive) setHandbook(book);
    }).catch(() => undefined);
    api<QuoteSource[]>("/api/quote-sources").then((rows) => {
      if (!alive) return;
      setQuoteSources(rows);
      setQuoteSource((current) => {
        const still = rows.find((item) => item.id === current && item.ready);
        const next = still?.id || rows.find((item) => item.ready)?.id || "";
        if (next) localStorage.setItem("td-quote-source", next);
        return next;
      });
    }).catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [user, reload]);

  useEffect(() => {
    if (selected == null && snap?.plans[0]) setSelected(snap.plans[0].id);
  }, [snap, selected]);

  function go(next: string) {
    location.hash = next;
    setTab(next);
  }

  if (!user) {
    return <Login onDone={(name) => { setUser(name); setError(""); }} notice={error} />;
  }

  const title = TABS.find(([id]) => id === tab)?.[1] || "今日看板";
  const danger = snap?.actions.filter((item) => item.level === "danger").length || 0;
  const gate: Gate | null = snap
    ? {
        asOf, setAsOf, snap, reload, selected, setSelected, go, draft, setDraft,
        quoteSources, quoteSource,
        setQuoteSource: (id: string) => {
          localStorage.setItem("td-quote-source", id);
          setQuoteSource(id);
        },
        report: (err) => {
          if (!err) { setError(""); return; }
          if (err instanceof ApiError && err.status === 401) { signOut("请先登录"); return; }
          setError(err instanceof Error ? err.message : "请求失败");
        },
      }
    : null;

  async function logout() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch { /* 本地会话一并清掉 */ }
    signOut();
  }

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <strong>交易纪律台</strong>
          <span>{snap?.version || "V2.0"} · {snap?.effective_on || "2026-11-19"}</span>
          <span>{snap?.priority || "账户安全 > 组合风险 > 单笔机会"}</span>
        </div>
        <nav className="nav">
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => go(id)}>
              {label}
              {id === "dashboard" && danger > 0 ? <span className="badge">{danger}</span> : null}
            </button>
          ))}
        </nav>
        <div className="side-foot">
          <div>{user}</div>
          <button className="nav-quiet" onClick={logout}>退出</button>
          <div>只记录和计算。行情只填写价格，不自动下单。</div>
        </div>
      </aside>
      <main className="main">
        <div className="top">
          <h1>{title}</h1>
          <label className="asof">
            核算日
            <input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
          </label>
        </div>
        {error ? <div className="banner">{error}</div> : null}
        {!gate ? <p>正在读取账本…</p> : null}
        {gate && tab === "market" ? <MarketPage gate={gate} /> : null}
        {gate && tab === "dashboard" ? <Dashboard gate={gate} /> : null}
        {gate && tab === "account" ? <AccountPage gate={gate} /> : null}
        {gate && tab === "plans" ? <PlansPage gate={gate} /> : null}
        {gate && tab === "trade" ? <TradePage gate={gate} /> : null}
        {gate && tab === "risk" ? <RiskPage gate={gate} /> : null}
        {gate && tab === "cooling" ? <CoolingPage gate={gate} /> : null}
        {gate && tab === "book" ? <BookPage gate={gate} /> : null}
        {gate && tab === "review" ? <ReviewPage gate={gate} /> : null}
        {gate && tab === "rules" ? <RulesPage gate={gate} handbook={handbook} /> : null}
        {snap ? <p className="foot">{snap.disclaimer}</p> : null}
      </main>
    </div>
  );
}

function Login({ onDone, notice }: { onDone: (username: string) => void; notice: string }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(notice);
  const [saving, setSaving] = useState(false);

  async function submit() {
    setSaving(true);
    setError("");
    try {
      const path = mode === "register" ? "/api/auth/register" : "/api/auth/login";
      const result = await api<{ token: string; user: { username: string } }>(path, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setAuth(result.token, result.user.username);
      onDone(result.user.username);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="login-wrap">
      <section className="card stack login">
        <h1>交易纪律台</h1>
        <p className="hint">每个人一份账本。行情用来填写价格，不会自动下单。</p>
        {error ? <div className="banner">{error}</div> : null}
        <label>用户名<input value={username} onChange={(event) => setUsername(event.target.value)} /></label>
        <label>密码<input type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>
        <button className="btn" disabled={saving} onClick={submit}>{mode === "register" ? "注册并进入" : "登录"}</button>
        <button className="btn secondary" type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "没有账号，注册" : "已有账号，登录"}
        </button>
      </section>
    </div>
  );
}
