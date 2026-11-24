export function localISO(day = new Date()): string {
  const y = day.getFullYear();
  const m = String(day.getMonth() + 1).padStart(2, "0");
  const d = String(day.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

export function money(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function px(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value.toLocaleString("zh-CN", { maximumFractionDigits: 4 });
}

export function shares(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return Number.isInteger(value) ? String(value) : value.toLocaleString("zh-CN", { maximumFractionDigits: 2 });
}

export function pct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

export const ASSETS: [string, string][] = [
  ["broad_etf", "宽基 ETF"],
  ["sector_etf", "行业 ETF"],
  ["large_cap", "大型成熟公司"],
  ["growth", "中小盘成长股"],
  ["high_vol", "高波动 / 亏损公司"],
];

export const REGIMES: [string, string][] = [
  ["defensive", "防守 · 40%"],
  ["neutral", "中性 · 60%"],
  ["aggressive", "积极 · 80%"],
  ["special_aggressive", "特殊积极 · 90%"],
];

export const COOLING: Record<string, string> = {
  reduction: "减仓后 10 个交易日",
  full_exit: "清仓后 20 个交易日",
  fundamental: "证伪后至少 20 个交易日",
};
