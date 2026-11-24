"""SQLite。成交、收盘和规则纪要只追加。"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
import json
from pathlib import Path

from td_core.params import V2

SCHEMA = """
CREATE TABLE IF NOT EXISTS account (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  nav TEXT NOT NULL DEFAULT '0',
  cash TEXT NOT NULL DEFAULT '0',
  nav_peak TEXT NOT NULL DEFAULT '0',
  peak_date TEXT,
  regime_intent TEXT NOT NULL DEFAULT 'neutral',
  regime_evidence TEXT NOT NULL DEFAULT '',
  special_reason TEXT NOT NULL DEFAULT '',
  special_exit TEXT NOT NULL DEFAULT '',
  special_started_on TEXT,
  trend_weakened INTEGER NOT NULL DEFAULT 0,
  assumption_failed INTEGER NOT NULL DEFAULT 0,
  risk_budget_pct TEXT NOT NULL DEFAULT '0.015',
  halt_new_until TEXT
);

CREATE TABLE IF NOT EXISTS nav_snapshots (
  id INTEGER PRIMARY KEY,
  as_of TEXT NOT NULL,
  nav TEXT NOT NULL,
  cash TEXT NOT NULL,
  nav_peak TEXT NOT NULL,
  drawdown TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS instruments (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  asset_type TEXT NOT NULL,
  industry TEXT NOT NULL DEFAULT '',
  theme TEXT NOT NULL DEFAULT '',
  high_vol INTEGER NOT NULL DEFAULT 0,
  liquidity_note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS plans (
  id INTEGER PRIMARY KEY,
  instrument_id INTEGER NOT NULL,
  thesis TEXT NOT NULL,
  catalyst TEXT NOT NULL,
  risks_json TEXT NOT NULL,
  invalidation TEXT NOT NULL,
  horizon TEXT NOT NULL,
  regime_snapshot TEXT NOT NULL,
  w_approved TEXT NOT NULL,
  w_max TEXT NOT NULL,
  entry_days INTEGER NOT NULL,
  reference_price TEXT,
  liquidity_ok INTEGER NOT NULL DEFAULT 0,
  abandoned INTEGER NOT NULL DEFAULT 0,
  structure_ok INTEGER NOT NULL DEFAULT 0,
  up_review_ok INTEGER NOT NULL DEFAULT 0,
  fundamental_veto INTEGER NOT NULL DEFAULT 0,
  veto_note TEXT NOT NULL DEFAULT '',
  industry_ok INTEGER NOT NULL DEFAULT 0,
  fundamental_ok INTEGER NOT NULL DEFAULT 0,
  reentry_w TEXT NOT NULL DEFAULT '0',
  new_fact TEXT NOT NULL DEFAULT '',
  missed_rebound TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY,
  plan_id INTEGER NOT NULL,
  side TEXT NOT NULL,
  trade_date TEXT NOT NULL,
  session TEXT NOT NULL,
  price TEXT NOT NULL,
  shares TEXT NOT NULL,
  amount TEXT NOT NULL,
  vwap TEXT,
  reason TEXT NOT NULL,
  slippage TEXT,
  off_rule INTEGER NOT NULL DEFAULT 0,
  off_rule_reason TEXT NOT NULL DEFAULT '',
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS marks (
  id INTEGER PRIMARY KEY,
  plan_id INTEGER NOT NULL,
  trade_date TEXT NOT NULL,
  price TEXT NOT NULL,
  source TEXT NOT NULL,
  kind TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS corporate_actions (
  id INTEGER PRIMARY KEY,
  instrument_id INTEGER NOT NULL,
  action_date TEXT NOT NULL,
  kind TEXT NOT NULL,
  price_factor TEXT NOT NULL,
  share_factor TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_reviews (
  id INTEGER PRIMARY KEY,
  week_ending TEXT NOT NULL,
  regime TEXT NOT NULL,
  exposure_note TEXT NOT NULL,
  correlation_note TEXT NOT NULL,
  decision TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_notes (
  id INTEGER PRIMARY KEY,
  version TEXT NOT NULL,
  note TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
  code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  market TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_versions (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  params_json TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: str):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def session(self):
        conn = self.connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with self.session() as conn:
            conn.executescript(SCHEMA)
            if conn.execute("SELECT id FROM account WHERE id = 1").fetchone() is None:
                conn.execute(
                    "INSERT INTO account (id, risk_budget_pct) VALUES (1, '0.015')"
                )
            if conn.execute("SELECT id FROM rule_notes WHERE version = 'V2.0'").fetchone() is None:
                conn.execute(
                    "INSERT INTO rule_notes (version, note, created_at) VALUES ('V2.0', ?, ?)",
                    (
                        "初始参数来自 2026-11-19 手册 V2.0。之后每次保存生成新版本，计算使用当前生效版本。",
                        "2026-11-19T00:00:00+08:00",
                    ),
                )
            if conn.execute("SELECT id FROM rule_versions").fetchone() is None:
                conn.execute(
                    """
                    INSERT INTO rule_versions (name, note, params_json, active, created_at)
                    VALUES ('V2.0', ?, ?, 1, ?)
                    """,
                    (
                        "手册默认值。这一行不会被覆盖，之后的修改另存为新版本。",
                        json.dumps(V2.to_dict(), ensure_ascii=False),
                        "2026-11-19T00:00:00+08:00",
                    ),
                )
