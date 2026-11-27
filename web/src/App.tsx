import { useCallback, useEffect, useState } from "react";
import { ApiError, api, clearAuth, setAuth, storedAdmin, storedUser } from "./api";
import { localISO } from "./format";
import { ActivityPage } from "./pages/Activity";
import { CashPage } from "./pages/Cash";
import { MarketPage } from "./pages/Market";
import { PositionsPage } from "./pages/Positions";
import { RulesPage } from "./pages/Rules";
import type { QuoteSource, Snapshot } from "./types";

const TABS = [
  ["market", "行情"],
  ["positions", "仓位"],
  ["cash", "现金"],
  ["rules", "规则"],
  ["activity", "操作记录"],
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
  admin: boolean;
};

export function App() {
  const [user, setUser] = useState(storedUser);
  const [admin, setAdmin] = useState(storedAdmin);
  const [tab, setTab] = useState(() => {
    const hash = location.hash.replace("#", "");
    return TABS.some(([id]) => id === hash) ? hash : "market";
  });
  const [draft, setDraft] = useState<{ code: string; name: string } | null>(null);
  const [asOf, setAsOf] = useState(localISO);
  const [snap, setSnap] = useState<Snapshot | null>(null);
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
    setAdmin(false);
    setSnap(null);
    setError(message);
  }

  useEffect(() => {
    if (!user) return;
    let alive = true;
    api<{ username: string; admin?: boolean }>("/api/auth/me")
      .then((me) => {
        setAdmin(Boolean(me.admin));
        localStorage.setItem("td-admin", me.admin ? "1" : "0");
        return reload();
      })
      .catch((err) => {
        if (!alive) return;
        if (err instanceof ApiError && err.status === 401) {
          signOut("请先登录");
          return;
        }
        setError(err instanceof Error ? err.message : "加载失败");
      });
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

  const title = TABS.find(([id]) => id === tab)?.[1] || "行情";
  const gate: Gate | null = snap
    ? {
        asOf, setAsOf, snap, reload, selected, setSelected, go, draft, setDraft,
        quoteSources, quoteSource, admin,
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
          <strong>行情与仓位</strong>
          <span>看价格，记持仓</span>
        </div>
        <nav className="nav">
          {TABS.map(([id, label]) => (
            <button key={id} className={tab === id ? "active" : ""} onClick={() => go(id)}>{label}</button>
          ))}
        </nav>
        <div className="side-foot">
          <div>{user}</div>
          <button className="nav-quiet" onClick={logout}>退出</button>
          <div>行情只填价格。记下一笔成交之后，才进入仓位。</div>
        </div>
      </aside>
      <main className="main">
        <div className="top">
          <h1>{title}</h1>
          <div className="top-actions">
            <label className="asof">
              日期
              <input type="date" value={asOf} onChange={(event) => setAsOf(event.target.value)} />
            </label>
            <button className="btn secondary top-logout" type="button" onClick={logout}>退出</button>
          </div>
        </div>
        {error ? <div className="banner">{error}</div> : null}
        {!gate ? <p>正在读取账本…</p> : null}
        {gate && tab === "market" ? <MarketPage gate={gate} /> : null}
        {gate && tab === "positions" ? <PositionsPage gate={gate} /> : null}
        {gate && tab === "cash" ? <CashPage gate={gate} /> : null}
        {gate && tab === "rules" ? <RulesPage gate={gate} /> : null}
        {gate && tab === "activity" ? <ActivityPage gate={gate} /> : null}
        {snap ? <p className="foot">{snap.disclaimer}</p> : null}
      </main>
      <nav className="tabbar" aria-label="页面">
        {TABS.map(([id, label]) => (
          <button key={id} className={tab === id ? "active" : ""} type="button" onClick={() => go(id)}>{label}</button>
        ))}
      </nav>
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
      const result = await api<{ token: string; user: { username: string; admin?: boolean } }>(path, {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      setAuth(result.token, result.user.username, Boolean(result.user.admin));
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
        <h1>行情与仓位</h1>
        <p className="hint">每个人一份账本。行情用来填价格，记账不会自动下单。</p>
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
