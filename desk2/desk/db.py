"""SQLite schema (STEP 4) + helpers. WAL mode. One connection per thread; the desk is one asyncio loop."""
from __future__ import annotations
import os, sqlite3, json, threading
from . import util

DB_PATH = os.environ.get("DESK_DB", os.path.join(util.ROOT, "desk.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS coins (mint TEXT PRIMARY KEY, name TEXT, symbol TEXT, pool TEXT, migrated_at TEXT,
  creator TEXT, creator_balance_at_migration REAL, holders INTEGER);
CREATE TABLE IF NOT EXISTS scans (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, ts TEXT, liquidity_usd REAL,
  top10_pct REAL, h1_change_pct REAL, age_min INTEGER, verdict TEXT, reason TEXT);
CREATE TABLE IF NOT EXISTS audits (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, ts TEXT, layer INTEGER, name TEXT,
  value_text TEXT, pass INTEGER, source TEXT);
CREATE TABLE IF NOT EXISTS verdicts (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, ts TEXT, alive_6h REAL, organic REAL,
  flush REAL, chase REAL, score INTEGER, pass INTEGER, reason TEXT, input_tokens INTEGER);
CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, ts TEXT, price REAL, size_usd REAL,
  stack_pct REAL, link TEXT, mode TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS positions (id INTEGER PRIMARY KEY AUTOINCREMENT, mint TEXT, opened_at TEXT, entry_price REAL,
  size_usd REAL, peak_price REAL, stop_price REAL, trail_active INTEGER DEFAULT 0, closed_at TEXT, exit_price REAL,
  exit_reason TEXT, pnl_usd REAL, fees_usd REAL, mode TEXT);
CREATE TABLE IF NOT EXISTS activity (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, mint TEXT, agent TEXT,
  title TEXT, subtitle TEXT, value TEXT);
CREATE TABLE IF NOT EXISTS prices (mint TEXT, ts TEXT, price REAL, volume_m5 REAL);
CREATE INDEX IF NOT EXISTS prices_mint_ts ON prices(mint, ts);
CREATE TABLE IF NOT EXISTS balance (ts TEXT, value REAL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS change_log (ts TEXT, key TEXT, old TEXT, new TEXT, who TEXT);
CREATE TABLE IF NOT EXISTS skips (mint TEXT, until TEXT);
CREATE TABLE IF NOT EXISTS heartbeats (agent TEXT PRIMARY KEY, ts TEXT);
CREATE TABLE IF NOT EXISTS push_subs (endpoint TEXT PRIMARY KEY, p256dh TEXT, auth TEXT, created_at TEXT);
-- additions (not in STEP 4): push history for the bell dot + the morning Page, and desk events for health
CREATE TABLE IF NOT EXISTS pushes (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, mint TEXT, kind TEXT, title TEXT,
  body TEXT, url TEXT, delivered INTEGER, seen INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, agent TEXT, mint TEXT, name TEXT,
  text TEXT, ok INTEGER);
CREATE TABLE IF NOT EXISTS agent_state (agent TEXT PRIMARY KEY, paused INTEGER, updated_at TEXT);
CREATE INDEX IF NOT EXISTS scans_mint ON scans(mint);
CREATE INDEX IF NOT EXISTS audits_mint ON audits(mint);
CREATE INDEX IF NOT EXISTS activity_ts ON activity(ts);
"""

_local = threading.local()

def conn() -> sqlite3.Connection:
    c = getattr(_local, "c", None)
    if c is None or getattr(_local, "path", None) != DB_PATH:
        c = sqlite3.connect(DB_PATH, timeout=30, isolation_level=None, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA synchronous=NORMAL")
        c.executescript(SCHEMA)
        cols = {r[1] for r in c.execute("PRAGMA table_info(coins)")}
        if "image" not in cols:   # addition: coin logo for pushes
            c.execute("ALTER TABLE coins ADD COLUMN image TEXT")
        _local.c, _local.path = c, DB_PATH
    return c

def use(path: str):
    """switch DB (tests)."""
    global DB_PATH
    DB_PATH = path
    _local.c = None

def q(sql: str, args=()) -> list[dict]:
    return [dict(r) for r in conn().execute(sql, args).fetchall()]

def one(sql: str, args=()) -> dict | None:
    r = conn().execute(sql, args).fetchone()
    return dict(r) if r else None

def x(sql: str, args=()) -> int:
    cur = conn().execute(sql, args)
    return cur.lastrowid

def insert(table: str, **kw) -> int:
    cols = ",".join(kw)
    return x(f"INSERT INTO {table} ({cols}) VALUES ({','.join('?'*len(kw))})", tuple(kw.values()))

def heartbeat(agent: str):
    x("INSERT INTO heartbeats(agent, ts) VALUES(?,?) ON CONFLICT(agent) DO UPDATE SET ts=excluded.ts", (agent, util.iso()))

def event(kind: str, detail="") :
    insert("events", ts=util.iso(), kind=kind, detail=detail if isinstance(detail, str) else json.dumps(detail))

def coin(mint: str) -> dict | None:
    return one("SELECT * FROM coins WHERE mint=?", (mint,))

def upsert_coin(mint: str, **kw):
    if not coin(mint):
        insert("coins", mint=mint, **kw)
    elif kw:
        sets = ",".join(f"{k}=?" for k in kw)
        x(f"UPDATE coins SET {sets} WHERE mint=?", (*kw.values(), mint))

def activity(kind, mint, agent, title, subtitle, value):
    return insert("activity", ts=util.iso(), kind=kind, mint=mint, agent=agent, title=title, subtitle=subtitle, value=value)

def price(mint, p, vol_m5):
    insert("prices", mint=mint, ts=util.iso(), price=p, volume_m5=vol_m5)

def decide(agent, mint, name, text, ok):
    insert("decisions", ts=util.iso(), agent=agent, mint=mint, name=name, text=text, ok=1 if ok else 0)

def paused(agent) -> bool:
    r = one("SELECT paused FROM agent_state WHERE agent=?", (agent,))
    return bool(r and r["paused"])

def set_paused(agent, v: bool):
    x("INSERT INTO agent_state(agent,paused,updated_at) VALUES(?,?,?) ON CONFLICT(agent) DO UPDATE SET paused=excluded.paused, updated_at=excluded.updated_at",
      (agent, 1 if v else 0, util.iso()))
