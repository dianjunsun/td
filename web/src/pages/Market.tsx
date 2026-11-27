import { useEffect, useRef, useState } from "react";
import type { Gate } from "../App";
import { api } from "../api";
import { money, pct, px } from "../format";
import { StockChart } from "./Chart";
import type { ChartSeries, Listing, Quote } from "../types";

const BOARDS = [
  ["gainers", "涨幅"],
  ["losers", "跌幅"],
  ["amount", "成交额"],
] as const;

const REFRESH = [
  [3000, "实时 · 3 秒"],
  [5000, "5 秒"],
  [15000, "15 秒"],
  [30000, "30 秒"],
  [60000, "60 秒"],
  [0, "关闭"],
] as const;

const PERIODS = [
  ["intraday", "分时"],
  ["intraday5", "五日"],
  ["day", "日K"],
  ["week", "周K"],
  ["month", "月K"],
] as const;

const WATCH_SOURCE = "eastmoney";

type WatchItem = { code: string; name: string; market: string };

export function MarketPage({ gate }: { gate: Gate }) {
  const source = gate.quoteSources.find((item) => item.id === gate.quoteSource);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<(typeof BOARDS)[number][0]>("gainers");
  const [mode, setMode] = useState<"board" | "search">("board");
  const [rows, setRows] = useState<Listing[]>([]);
  const [watch, setWatch] = useState<Listing[]>([]);
  const [saved, setSaved] = useState<string[]>([]);
  const [picked, setPicked] = useState<Listing | null>(null);
  const [detail, setDetail] = useState<Quote | null>(null);
  const [period, setPeriod] = useState(() => {
    const saved = localStorage.getItem("td-chart-period");
    return PERIODS.some(([id]) => id === saved) ? saved || "intraday" : "intraday";
  });
  const [chart, setChart] = useState<ChartSeries | null>(null);
  const [chartNote, setChartNote] = useState("");
  const [refreshMs, setRefreshMs] = useState(() => {
    const raw = localStorage.getItem("td-refresh-ms");
    const stored = raw == null ? 3000 : Number(raw);
    return REFRESH.some(([ms]) => ms === stored) ? stored : 3000;
  });
  const [refreshedAt, setRefreshedAt] = useState("");
  const live = useRef({ mode, sort, source: gate.quoteSource, hasBoard: Boolean(source?.board), code: "", period, rowCodes: [] as string[], saved: [] as string[] });
  live.current = {
    mode, sort, source: gate.quoteSource, hasBoard: Boolean(source?.board),
    code: picked?.code || "",
    period,
    rowCodes: rows.map((row) => row.code),
    saved,
  };

  async function loadWatch(items: WatchItem[]) {
    setSaved(items.map((item) => item.code));
    setWatch((current) => items.map((item) => current.find((row) => row.code === item.code) || emptyListing(item)));
    if (!items.length) return;
    try {
      const quotes = await api<Listing[]>("/api/market/quotes", {
        method: "POST",
        body: JSON.stringify({ source: WATCH_SOURCE, codes: items.map((item) => item.code) }),
      });
      const byCode = new Map(quotes.map((item) => [item.code, item]));
      setWatch(items.map((item) => byCode.get(item.code) || emptyListing(item)));
    } catch (error) {
      gate.report(error);
    }
  }

  useEffect(() => {
    let alive = true;
    api<WatchItem[]>("/api/watchlist")
      .then((items) => { if (alive) return loadWatch(items); })
      .catch((error) => { if (alive) gate.report(error); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!gate.quoteSource || !source?.board) {
      setMode("search");
      setRows([]);
      return;
    }
    let alive = true;
    setMode("board");
    api<Listing[]>(`/api/market/board?source=${encodeURIComponent(gate.quoteSource)}&sort=${sort}`)
      .then((list) => {
        if (!alive) return;
        setRows(list);
        setPicked((current) => current || list[0] || null);
        gate.report("");
      })
      .catch((error) => { if (alive) gate.report(error); });
    return () => { alive = false; };
  }, [gate.quoteSource, source?.board, sort]);

  useEffect(() => {
    if (!picked || !gate.quoteSource) {
      setDetail(null);
      return;
    }
    let alive = true;
    setChart(null);
    setChartNote("");
    api<Quote>(`/api/quotes/${encodeURIComponent(picked.code)}?source=${encodeURIComponent(gate.quoteSource)}`)
      .then((quote) => { if (alive) setDetail(quote); })
      .catch(() => { if (alive) setDetail(null); });
    api<ChartSeries>(`/api/market/chart?code=${encodeURIComponent(picked.code)}&source=${encodeURIComponent(gate.quoteSource)}&period=${encodeURIComponent(period)}`)
      .then((series) => { if (!alive) return; setChart(series); setChartNote(""); })
      .catch((error) => { if (!alive) return; setChart(null); setChartNote(error instanceof Error ? error.message : "K线没有取到"); });
    return () => { alive = false; };
  }, [picked?.code, gate.quoteSource, period]);

  useEffect(() => {
    if (!refreshMs || !gate.quoteSource) return;
    let stopped = false;
    async function tick() {
      if (stopped || document.hidden) return;
      const snap = live.current;
      if (!snap.source) return;
      try {
        if (snap.code) {
          const quote = await api<Quote>(`/api/quotes/${encodeURIComponent(snap.code)}?source=${encodeURIComponent(snap.source)}`);
          if (stopped) return;
          setDetail(quote);
        }
        if (snap.mode === "board" && snap.hasBoard) {
          const list = await api<Listing[]>(`/api/market/board?source=${encodeURIComponent(snap.source)}&sort=${snap.sort}`);
          if (!stopped) setRows(list);
        } else if (snap.rowCodes.length) {
          const quotes = await api<Listing[]>("/api/market/quotes", {
            method: "POST",
            body: JSON.stringify({ source: snap.source, codes: snap.rowCodes }),
          });
          if (!stopped) setRows((current) => mergeQuotes(current, quotes));
        }
        if (!stopped) setRefreshedAt(new Date().toLocaleTimeString("zh-CN", { hour12: false }));
      } catch {
        /* 下一轮再试，保留上一次成功的时间 */
      }
      if (!stopped && snap.code && snap.period) {
        api<ChartSeries>(`/api/market/chart?code=${encodeURIComponent(snap.code)}&source=${encodeURIComponent(snap.source)}&period=${encodeURIComponent(snap.period)}`)
          .then((series) => {
            if (stopped || series.period !== live.current.period || snap.code !== live.current.code) return;
            setChart(series);
            setChartNote("");
          })
          .catch((error) => {
            if (stopped || snap.period !== live.current.period) return;
            setChartNote(error instanceof Error ? error.message : "K线没有取到");
          });
      }
      if (stopped || !snap.saved.length) return;
      try {
        const quotes = await api<Listing[]>("/api/market/quotes", {
          method: "POST",
          body: JSON.stringify({ source: WATCH_SOURCE, codes: snap.saved }),
        });
        if (!stopped) setWatch((current) => mergeQuotes(current, quotes));
      } catch {
        /* 自选报价失败时保留原来的名单和数字 */
      }
    }
    const timer = window.setInterval(tick, refreshMs);
    function onVisible() {
      if (!document.hidden) tick();
    }
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [refreshMs, gate.quoteSource]);

  function listEmpty() {
    if (mode === "search" && query.trim()) return "没有搜索结果";
    if (!source?.board) return `${source?.label || "当前行情源"}没有涨跌榜。用代码或名称搜索，表格仍是这一套。`;
    return "榜单还没回来";
  }

  async function search() {
    try {
      const list = await api<Listing[]>(`/api/market/search?q=${encodeURIComponent(query.trim())}&source=${encodeURIComponent(gate.quoteSource)}`);
      setMode("search");
      setRows(list);
      setPicked(list[0] || null);
      gate.report("");
      if (!list.length) return;
      const quotes = await api<Listing[]>("/api/market/quotes", {
        method: "POST",
        body: JSON.stringify({ source: gate.quoteSource, codes: list.map((item) => item.code) }),
      });
      setRows(mergeQuotes(list, quotes));
    } catch (error) {
      gate.report(error);
    }
  }

  async function toggleWatch(row: Listing) {
    try {
      const items = saved.includes(row.code)
        ? await api<WatchItem[]>(`/api/watchlist/${encodeURIComponent(row.code)}`, { method: "DELETE" })
        : await api<WatchItem[]>("/api/watchlist", {
            method: "POST",
            body: JSON.stringify({ code: row.code, name: row.name, market: row.market }),
          });
      await loadWatch(items);
      gate.report("");
    } catch (error) {
      gate.report(error);
    }
  }

  const price = detail ? num(detail.price) : picked?.price ?? null;
  const prev = detail ? num(detail.prev_close) : picked?.prev_close ?? null;
  const changePct = (detail ? num(detail.change_pct) : null) ?? picked?.change_pct ?? (price != null && prev ? price / prev - 1 : null);
  const change = (detail ? num(detail.change) : null) ?? picked?.change ?? (price != null && prev != null ? price - prev : null);
  const amount = (detail ? num(detail.amount) : null) ?? picked?.amount ?? null;
  const tone = changePct == null ? "flat" : changePct > 0 ? "rise" : changePct < 0 ? "fall" : "flat";

  return (
    <div className="market">
      <section className="card stack market-list">
        <div className="toolbar">
          <label>行情源
            <select value={gate.quoteSource} onChange={(event) => gate.setQuoteSource(event.target.value)}>
              {gate.quoteSources.map((item) => (
                <option key={item.id} value={item.id} disabled={!item.ready}>{item.ready ? item.label : `${item.label}（未配置）`}</option>
              ))}
            </select>
          </label>
          <label>刷新
            <select value={String(refreshMs)} onChange={(event) => {
              const next = Number(event.target.value);
              localStorage.setItem("td-refresh-ms", String(next));
              setRefreshMs(next);
            }}>
              {REFRESH.map(([ms, label]) => <option key={ms} value={ms}>{label}</option>)}
            </select>
          </label>
          <div className="search-line">
            <label>搜索
              <input value={query} placeholder="代码或名称，例如 600519、茅台" onChange={(event) => setQuery(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") search(); }} />
            </label>
            <button className="btn secondary" type="button" onClick={search}>搜索</button>
          </div>
        </div>
        <p className="hint">{refreshMs ? `每 ${refreshMs / 1000} 秒向${source?.label || "当前行情源"}拉一次正在看的报价、榜单和当前这张图` : "自动刷新已关闭"}{refreshedAt ? ` · 上次 ${refreshedAt}` : ""}。</p>
        <div className="row">
          {BOARDS.map(([id, label]) => (
            <button key={id} className={`btn ${source?.board && mode === "board" && sort === id ? "" : "secondary"}`} type="button" disabled={!source?.board} onClick={() => setSort(id)}>{label}</button>
          ))}
        </div>
        <div className="table-wrap"><Board rows={rows} picked={picked?.code || ""} onPick={setPicked} empty={listEmpty()} /></div>
        <h2>自选</h2>
        <p className="hint">自选名单存在你的账本里，不跟行情源走。这里的最新价固定用东方财富，每轮刷新只更新数字。</p>
        <div className="table-wrap"><Board rows={watch} picked={picked?.code || ""} onPick={setPicked} empty="还没有自选。从上面点一只，再加入。" /></div>
      </section>
      <section className="card stack market-detail">
        {!picked ? <p className="hint">点一只股票，这里看报价和 K 线。</p> : (
          <>
            <h2>{picked.name} {picked.code}</h2>
            <div className={`quote-hero ${tone}`}>{px(price)}</div>
            <p className={tone}>{pct(changePct)} {change == null ? "" : money(change)}</p>
            <div className="segments">
              {PERIODS.map(([id, label]) => (
                <button key={id} className={`btn ${period === id ? "" : "secondary"}`} type="button" onClick={() => { localStorage.setItem("td-chart-period", id); setPeriod(id); }}>{label}</button>
              ))}
            </div>
            {chart?.bars.length ? (
              <StockChart bars={chart.bars} kind={period.startsWith("intraday") ? "line" : "candle"} prevClose={chart.prev_close ?? (detail ? num(detail.prev_close) : null)} resetKey={`${picked.code}|${gate.quoteSource}|${period}`} />
            ) : <div className="chart-empty"><p className="hint">{chartNote || "K线还没回来"}</p></div>}
            <p className="hint">{chart?.bars.length ? `${chart.label}${chart.adjust ? ` · ${chart.adjust}` : ""} · ${chart.bars[0].trade_date} 至 ${chart.bars[chart.bars.length - 1].trade_date}` : "K线 · 暂无"}。拖动平移，滚轮缩放。</p>
            <div className="grid">
              <div><div className="hint">开盘</div><div>{px(detail ? num(detail.open) : picked.open)}</div></div>
              <div><div className="hint">最高</div><div>{px(detail ? num(detail.high) : picked.high)}</div></div>
              <div><div className="hint">最低</div><div>{px(detail ? num(detail.low) : picked.low)}</div></div>
              <div><div className="hint">昨收</div><div>{px(detail ? num(detail.prev_close) : picked.prev_close)}</div></div>
              <div><div className="hint">成交额</div><div>{money(amount)}</div></div>
              <div><div className="hint">VWAP</div><div>{detail?.vwap ? detail.vwap : "—"}</div></div>
            </div>
            <p className="hint">{detail ? `${detail.source_label} ${detail.as_of}` : source?.label}。看盘不改账本，记入仓位之后才入账。</p>
            <div className="row">
              <button className="btn secondary" type="button" onClick={() => toggleWatch(picked)}>{saved.includes(picked.code) ? "移出自选" : "加入自选"}</button>
              <button className="btn" type="button" onClick={() => { gate.setDraft({ code: picked.code, name: picked.name }); gate.go("positions"); }}>记入仓位</button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function mergeQuotes(current: Listing[], quotes: Listing[]): Listing[] {
  const byCode = new Map(quotes.map((item) => [item.code, item]));
  return current.map((item) => {
    const next = byCode.get(item.code);
    return next ? { ...item, ...next, name: next.name || item.name } : item;
  });
}

function Board({ rows, picked, onPick, empty }: { rows: Listing[]; picked: string; onPick: (row: Listing) => void; empty: string }) {
  return (
    <table className="board">
      <thead>
        <tr><th>名称</th><th className="num">最新</th><th className="num">涨跌</th><th className="num">成交额</th></tr>
      </thead>
      <tbody>
        {!rows.length ? <tr><td colSpan={4} className="hint">{empty}</td></tr> : null}
        {rows.map((row) => {
          const tone = row.change_pct == null ? "" : row.change_pct > 0 ? "rise" : row.change_pct < 0 ? "fall" : "";
          return (
            <tr key={row.code} className={row.code === picked ? "active" : ""} onClick={() => onPick(row)}>
              <td>{row.name}<div className="hint">{row.code}</div></td>
              <td className={`num ${tone}`}>{px(row.price)}</td>
              <td className={`num ${tone}`}>{pct(row.change_pct)}</td>
              <td className="num">{money(row.amount)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function emptyListing(item: WatchItem): Listing {
  return {
    code: item.code, market: item.market, name: item.name,
    price: null, change: null, change_pct: null, amount: null,
    open: null, high: null, low: null, prev_close: null,
  };
}

function num(value: string | null | undefined): number | null {
  if (value == null || value === "") return null;
  const parsed = Number(value);
  return Number.isNaN(parsed) ? null : parsed;
}
