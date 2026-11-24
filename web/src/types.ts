export type Action = {
  level: "danger" | "warn" | "plan" | "info";
  code: string;
  title: string;
  detail: string;
  plan_id: number | null;
  shares: number | null;
  amount: number | null;
};

export type View = {
  entry_state: string;
  entry_label: string;
  next_buy_amount: number;
  slices: number[];
  slice_index: number;
  slice_in_progress: boolean;
  allowed_total: number;
  filled_amount: number;
  shares: number;
  original_shares: number;
  sold_shares: number;
  p0: number | null;
  c: number | null;
  h: number | null;
  r: number | null;
  last_price: number | null;
  last_date: string | null;
  last_kind: string | null;
  close_price: number | null;
  drawdown: number | null;
  tier: number;
  tier_prices: { d10: number | null; d15: number | null; d20: number | null };
  sell_need: number;
  lines: { up: number; pause: number; cancel: number; reclaim: number } | null;
  lines_preview: boolean;
  cooling_kind: string | null;
  cooling_start: string | null;
  cooling_until: string | null;
  cooling_active: boolean;
  breakdown: number | null;
  p0_cancelled: boolean;
  market_value: number;
  profit_band: string;
  profit_label: string;
  protection_floor: number | null;
  overweight_shares: number;
  rebalance_due: string | null;
  rebalance_overdue: boolean;
  realized_pnl: number | null;
  flat_date: string | null;
  unrealized_pnl: number | null;
  reentry_spent: number;
  await_close: boolean;
  warnings: string[];
};

export type Fill = {
  id: number;
  plan_id: number;
  code: string;
  name: string;
  side: string;
  trade_date: string;
  session: string;
  price: number;
  shares: number;
  amount: number;
  vwap: number | null;
  reason: string;
  slippage: number | null;
  off_rule: boolean;
  off_rule_reason: string;
  note: string;
};

export type Mark = {
  id: number;
  trade_date: string;
  price: number;
  source: string;
  kind: string;
  note: string;
};

export type Plan = {
  id: number;
  instrument_id: number;
  code: string;
  name: string;
  asset_type: string;
  asset_label: string;
  industry: string;
  theme: string;
  high_vol: boolean;
  asset_cap: number;
  thesis: string;
  catalyst: string;
  risks: string[];
  invalidation: string;
  horizon: string;
  regime_snapshot: string;
  w_approved: number;
  w_max: number;
  entry_days: number;
  reference_price: number | null;
  abandoned: boolean;
  structure_ok: boolean;
  up_review_ok: boolean;
  fundamental_veto: boolean;
  veto_note: string;
  industry_ok: boolean;
  fundamental_ok: boolean;
  reentry_w: number;
  new_fact: string;
  missed_rebound: number | null;
  created_at: string;
  weight: number | null;
  view: View;
  fills: Fill[];
  marks: Mark[];
};

export type Instrument = {
  id: number;
  code: string;
  name: string;
  asset_type: string;
  asset_label: string;
  industry: string;
  theme: string;
  high_vol: boolean;
  asset_cap: number;
  liquidity_note: string;
};

export type Snapshot = {
  as_of: string;
  version: string;
  effective_on: string;
  priority: string;
  disclaimer: string;
  account: {
    nav: number;
    cash: number;
    nav_peak: number;
    peak_date: string | null;
    drawdown: number | null;
    regime_intent: string;
    regime_intent_label: string;
    effective_regime: string;
    effective_regime_label: string;
    regime_cap: number;
    regime_evidence: string;
    special_reason: string;
    special_exit: string;
    special_started_on: string | null;
    special_last_day: string | null;
    trend_weakened: boolean;
    assumption_failed: boolean;
    risk_budget_pct: number;
    halt_new_until: string | null;
    halt_active: boolean;
    regime_reasons: string[];
    suggested_nav: number;
    calendar_warning: string | null;
  };
  portfolio: {
    gross_value: number;
    gross_weight: number | null;
    industries: { name: string; value: number; weight: number | null }[];
    themes: { name: string; value: number; weight: number | null }[];
    high_vol_value: number;
    high_vol_weight: number | null;
    industry_cap: number;
    high_vol_cap: number;
  };
  actions: Action[];
  plans: Plan[];
  instruments: Instrument[];
  recent_fills: Fill[];
  weekly: {
    id: number;
    week_ending: string;
    regime: string;
    regime_label: string;
    exposure_note: string;
    correlation_note: string;
    decision: string;
    created_at: string;
  }[];
  quarterly: {
    evaluation_ready: boolean;
    progress: number;
    required: number;
    off_rule_count: number;
    fill_count: number;
    reminder: string;
    off_rule_limit: number;
    stats: null | {
      win_rate: number;
      avg_win: number;
      avg_loss: number;
      payoff: number | null;
      expectancy: number;
      max_consecutive_losses: number;
      max_account_drawdown: number | null;
      missed_rebound: number | null;
      missed_coverage: string;
      avg_slippage: number | null;
      off_rule_ratio: number;
      expectancy_positive: boolean;
      off_rule_below_5pct: boolean;
    };
    closed_trades: {
      plan_id: number;
      code: string;
      name: string;
      pnl: number;
      flat_date: string;
      missed: number | null;
      off_rule_fills: number;
    }[];
  };
  rule_notes: { id: number; version: string; note: string; created_at: string }[];
  rule: RuleSummary;
};

export type RuleParams = {
  asset_caps: Record<string, number>;
  industry_cap: number;
  high_vol_group_cap: number;
  regime_caps: Record<string, number>;
  neutral_executable: number;
  risk_budget_default: number;
  risk_budget_max: number;
  path_legs: { weight: number; loss: number }[];
  broad_etf_uses_cap_when_aggressive: boolean;
  schedules: number[][];
  anchor_multiple: number;
  profit_floor_multiple: number;
  run_multiple: number;
  tier_drawdowns: number[];
  tier_fractions: number[];
  p0_up: number;
  p0_pause: number;
  p0_cancel: number;
  p0_reclaim: number;
  chase_multiple: number;
  spike_stable_days: number;
  cooling_reduction_days: number;
  cooling_exit_days: number;
  special_max_days: number;
  account_dd_downgrade: number;
  account_dd_defensive: number;
  account_dd_halt: number;
  halt_days: number;
  rebalance_days: number;
  intraday_auto_tier: number;
  sell_tolerance_shares: number;
  sell_tolerance_pct: number;
  min_sample: number;
  off_rule_limit: number;
};

export type RuleSummary = {
  id: number;
  name: string;
  note: string;
  created_at: string;
  active: boolean;
  params: RuleParams;
  schedules: { days: number; label: string }[];
  path_loss: number;
  risk_budget_default: number;
  risk_budget_max: number;
  cooling_reduction_days: number;
  cooling_exit_days: number;
  off_rule_limit: number;
  p0_cancel: number;
};

export type QuoteSource = {
  id: string;
  label: string;
  ready: boolean;
  note: string;
  search: boolean;
  board: boolean;
};

export type Listing = {
  code: string;
  market: string;
  name: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  amount: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  prev_close: number | null;
};

export type Bar = {
  trade_date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  avg?: number | null;
};

export type DailySeries = {
  adjust: string;
  bars: Bar[];
};

export type ChartSeries = {
  period: string;
  label: string;
  adjust: string;
  prev_close: number | null;
  bars: Bar[];
};

export type Quote = {
  code: string;
  name: string;
  price: string;
  open: string | null;
  high: string | null;
  low: string | null;
  prev_close: string | null;
  vwap: string | null;
  change: string | null;
  change_pct: string | null;
  amount: string | null;
  as_of: string;
  source_label: string;
};

export type Handbook = {
  version: string;
  effective_on: string;
  priority: string[];
  disclaimer: string;
  sections: { title: string; items: string[] }[];
};

export type Preview = {
  w_max: number | null;
  cap_amount: number | null;
  risk_amount: number | null;
  executable_now: number | null;
  multiplier: number | null;
  slices: number[];
  entry_lines: { up: number; pause: number; cancel: number; reclaim: number } | null;
  tier_preview: { tier: number; sell_fraction: number; price: number | null }[];
  notes: string[];
  errors: string[];
};
