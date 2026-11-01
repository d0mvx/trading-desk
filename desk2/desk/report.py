"""STEP 12: morning Page content. Red trades first, then green; coins seen; Scanner kills by reason; Auditor refusals
by layer with times; Analyst rejects with the failed rule; Jev tokens + cost; fees paid; health. Every coin linked
with links.coin_url. --clear-skips empties db.skips after the report. NO routine is created here (the parent schedules).
usage: python -m desk.report [--current] [--clear-skips] [--out FILE.md] [--html FILE.html]"""
from __future__ import annotations
import argparse, datetime as dt, html as H, os, re
from collections import Counter, defaultdict
from . import db, util, config, links, account

JEV_PER_M_INPUT = 0.042   # $ per 1M input tokens (STEP 12)

def window(current: bool = False):
    rt = config.get("desk.report_time")
    end = util.night_start(rt)
    if current:
        return end, util.now() + dt.timedelta(seconds=1)
    return end - dt.timedelta(days=1), end

def _nm(m):
    c = db.coin(m) or {}
    return c.get("symbol") or c.get("name") or util.short(m)

def _ln(m):
    return f"[{_nm(m)}]({links.coin_url(m)})"

def data(current=False):
    a, b = window(current)
    A, B = util.iso(a), util.iso(b)
    trades = db.q("SELECT * FROM positions WHERE opened_at>=? AND opened_at<?", (A, B))
    closed = [t for t in trades if t["closed_at"]]
    red = sorted([t for t in closed if (t["pnl_usd"] or 0) < 0], key=lambda t: t["pnl_usd"])
    green = sorted([t for t in closed if (t["pnl_usd"] or 0) >= 0], key=lambda t: -t["pnl_usd"])
    opn = [t for t in trades if not t["closed_at"]]
    seen = db.q("SELECT * FROM coins WHERE migrated_at>=? AND migrated_at<?", (A, B))
    kills = db.q("SELECT mint, ts, reason, verdict FROM scans WHERE ts>=? AND ts<? AND verdict IN ('kill','drop')", (A, B))
    passes = db.q("SELECT mint, ts, reason FROM scans WHERE ts>=? AND ts<? AND verdict='pass'", (A, B))
    by_reason = defaultdict(list)
    for k in kills:
        r = re.sub(r"[\d$.,%+K M]+$", "", k["reason"]).strip() or k["reason"]
        r = r.split(" of ")[0] if r.startswith("copycat") else r
        by_reason[r].append(k)
    refusals = db.q("SELECT mint, ts, layer, name, value_text FROM audits WHERE ts>=? AND ts<? AND pass=0 ORDER BY layer, ts", (A, B))
    verdicts = db.q("SELECT * FROM verdicts WHERE ts>=? AND ts<?", (A, B))
    tokens = sum(v["input_tokens"] or 0 for v in verdicts)
    fees_paid = sum(t["fees_usd"] or 0 for t in trades)
    pnl = sum(t["pnl_usd"] or 0 for t in closed)
    hb = db.q("SELECT * FROM heartbeats")
    ev = Counter(e["kind"] for e in db.q("SELECT kind FROM events WHERE ts>=? AND ts<?", (A, B)))
    bal = db.q("SELECT value FROM balance WHERE ts>=? AND ts<? ORDER BY ts", (A, B))
    return dict(a=a, b=b, red=red, green=green, open=opn, seen=seen, kills=kills, by_reason=by_reason, passes=passes,
                refusals=refusals, verdicts=verdicts, tokens=tokens, jev_cost=tokens / 1e6 * JEV_PER_M_INPUT, fees=fees_paid,
                pnl=pnl, hb=hb, events=ev, bal_start=bal[0]["value"] if bal else None, bal_end=bal[-1]["value"] if bal else None,
                mode=config.get("desk.mode"))

def _t(iso_s):
    return util.local_hm(iso_s)

def markdown(current=False) -> str:
    d = data(current)
    L = []
    w = f"{d['a'].astimezone(util.TZ):%a %d %b %H:%M} → {d['b'].astimezone(util.TZ):%a %d %b %H:%M} (Berlin)"
    L.append(f"# Desk night report · {d['mode']}")
    L.append(f"{w}\n")
    L.append(f"**PnL {'+' if d['pnl'] >= 0 else '-'}${abs(d['pnl']):,.2f}** · {len(d['red']) + len(d['green'])} closed trades · "
             f"balance {util.money(d['bal_start'])} → {util.money(d['bal_end'])} · equity now ${account.equity():,.2f}\n")
    L.append("## Trades (red first)")
    if not (d["red"] or d["green"] or d["open"]):
        L.append("No trades.")
    for t in d["red"] + d["green"]:
        L.append(f"- {'🔴' if t['pnl_usd'] < 0 else '🟢'} {_ln(t['mint'])} · ${t['size_usd']:,.2f} · {t['exit_reason']} · "
                 f"entry {t['entry_price']:.8g} → exit {t['exit_price']:.8g} · "
                 f"{'+' if t['pnl_usd'] >= 0 else '-'}${abs(t['pnl_usd']):,.2f} ({t['pnl_usd'] / t['size_usd'] * 100:+.1f}%) · fees ${t['fees_usd']:,.2f} · "
                 f"{_t(t['opened_at'])}–{_t(t['closed_at'])}")
    for t in d["open"]:
        L.append(f"- ⚪ {_ln(t['mint'])} · ${t['size_usd']:,.2f} · still open since {_t(t['opened_at'])}")
    L.append(f"\n## Coins seen: {len(d['seen'])}")
    L.append(f"Passed Scanner: {len(d['passes'])}" + (" · " + ", ".join(_ln(p['mint']) for p in d["passes"]) if d["passes"] else ""))
    L.append("\n## Scanner kills by reason")
    if not d["by_reason"]:
        L.append("None.")
    for r, ks in sorted(d["by_reason"].items(), key=lambda kv: -len(kv[1])):
        L.append(f"- **{r}** × {len(ks)}: " + ", ".join(f"{_ln(k['mint'])} ({k['reason']}, {_t(k['ts'])})" for k in ks[:25]) +
                 (f" … +{len(ks) - 25}" if len(ks) > 25 else ""))
    L.append("\n## Auditor refusals by layer")
    if not d["refusals"]:
        L.append("None.")
    by_layer = defaultdict(list)
    for r in d["refusals"]:
        by_layer[(r["layer"], r["name"])].append(r)
    for (n, nm), rs in sorted(by_layer.items()):
        L.append(f"- **{n} {nm}** × {len(rs)}: " + ", ".join(f"{_ln(r['mint'])} {r['value_text']} at {_t(r['ts'])}" for r in rs))
    L.append("\n## Analyst")
    rej = [v for v in d["verdicts"] if not v["pass"]]
    L.append(f"{len(d['verdicts'])} scored · {len(d['verdicts']) - len(rej)} passed · {len(rej)} rejected")
    for v in rej:
        L.append(f"- {_ln(v['mint'])} score {v['score']} · {(v['reason'] or '').split(';')[0]} at {_t(v['ts'])}")
    L.append(f"\nJev input tokens {d['tokens']:,} · cost ${d['jev_cost']:.4f} (at ${JEV_PER_M_INPUT}/1M input)")
    L.append(f"Fees + slippage paid (model, fees.py): ${d['fees']:,.2f}")
    L.append("\n## Health")
    for h in d["hb"]:
        age = (util.now() - util.parse(h["ts"])).total_seconds()
        L.append(f"- {h['agent']}: last beat {_t(h['ts'])} ({'ok' if age < 180 else f'STALE {age / 60:.0f} min'})")
    if d["events"]:
        L.append("- events: " + ", ".join(f"{k} × {v}" for k, v in d["events"].items()))
    L.append(f"\nNew to {links.VENUE}? {links.SIGNUP_URL}")
    return "\n".join(L)

def html(current=True) -> str:
    md = markdown(current)
    out = []
    for line in md.split("\n"):
        e = H.escape(line)
        e = re.sub(r"\[([^\]]+)\]\((https://[^)]+)\)", r'<a href="\2">\1</a>', e)
        e = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", e)
        if e.startswith("# "): out.append(f"<h1>{e[2:]}</h1>")
        elif e.startswith("## "): out.append(f"<h2>{e[3:]}</h2>")
        elif e.startswith("- "): out.append(f"<li>{e[2:]}</li>")
        elif e: out.append(f"<p>{e}</p>")
    return ("<!doctype html><meta charset=utf-8><meta name=viewport content='width=device-width'><style>body{background:#000;color:#fff;"
            "font:15px -apple-system,system-ui;padding:16px}a{color:#64d2ff}li{margin:4px 0}</style>" + "\n".join(out))

def clear_skips():
    db.x("DELETE FROM skips")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--current", action="store_true", help="the night in progress instead of the last finished one")
    ap.add_argument("--clear-skips", action="store_true")
    ap.add_argument("--out"); ap.add_argument("--html")
    a = ap.parse_args()
    md = markdown(a.current)
    if a.out: open(a.out, "w").write(md)
    if a.html: open(a.html, "w").write(html(a.current))
    print(md)
    if a.clear_skips:
        clear_skips()
