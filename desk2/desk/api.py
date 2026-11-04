"""STEP 7 API. Every /api route needs APP_TOKEN (Authorization: Bearer), else 401.
The token reaches the app only via {URL}#t={APP_TOKEN} -> localStorage. SSE is read with fetch() so the
token travels in a header, never in a URL/log. Static web/ is public (no data in it)."""
from __future__ import annotations
import asyncio, datetime as dt, hmac, json, os, time
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import db, util, config, bus, links, account, webpush, commands, sources as S, chain, report
from .agents import risk as risk_agent

WEB = os.path.join(os.path.dirname(__file__), "web")
AGENTS = ["scanner", "auditor", "analyst", "executor", "risk"]
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

def _token():
    return util.secret("app_token") or ""

def auth(request: Request):
    h = request.headers.get("authorization", "")
    tok = h[7:] if h.lower().startswith("bearer ") else ""
    if not tok or not hmac.compare_digest(tok, _token()):
        raise HTTPException(401, "unauthorized")

A = [Depends(auth)]

@app.middleware("http")
async def headers(request: Request, call_next):
    r = await call_next(request)
    r.headers["cache-control"] = "no-store" if request.url.path.startswith("/api") or request.url.path in ("/", "/index.html", "/sw.js") else "public, max-age=300"
    r.headers["x-content-type-options"] = "nosniff"
    r.headers["referrer-policy"] = "no-referrer"
    return r

# ---------- helpers
def night_iso():
    return util.iso(util.night_start(config.get("desk.report_time")))

def name_of(m):
    c = db.coin(m) or {}
    return c.get("symbol") or c.get("name") or util.short(m)

def act_rows(rows):
    return [{**r, "link": links.coin_url(r["mint"]) if r["mint"] else None, "time": util.local_hm(r["ts"])} for r in rows]

def night_start_balance():
    r = db.one("SELECT value FROM balance WHERE ts>=? ORDER BY ts LIMIT 1", (night_iso(),))
    return r["value"] if r else account.equity()

def agents_summary():
    n = night_iso()
    s = config.all_settings()
    hb = {r["agent"]: r["ts"] for r in db.q("SELECT * FROM heartbeats")}
    from .agents import scanner
    kills = db.q("SELECT s.mint, s.reason, s.verdict, c.symbol FROM scans s LEFT JOIN coins c ON c.mint=s.mint WHERE s.ts>=? AND s.verdict IN ('kill','pass','drop') ORDER BY s.id DESC LIMIT 4", (n,))
    pools = db.one("SELECT COUNT(DISTINCT mint) n FROM scans WHERE ts>=?", (n,))["n"]
    taken = db.one("SELECT COUNT(DISTINCT mint) n FROM audits WHERE ts>=?", (n,))["n"]
    rejected = db.one("SELECT COUNT(DISTINCT mint) n FROM audits WHERE ts>=? AND pass=0", (n,))["n"]
    last_audit = db.one("SELECT mint FROM audits WHERE ts>=? ORDER BY id DESC LIMIT 1", (n,))
    layers = db.q("SELECT layer,name,value_text,pass FROM audits WHERE mint=? ORDER BY id DESC LIMIT 8", (last_audit["mint"],)) if last_audit else []
    v = db.one("SELECT v.*, c.symbol FROM verdicts v LEFT JOIN coins c ON c.mint=v.mint WHERE v.ts>=? ORDER BY v.id DESC LIMIT 1", (n,))
    trades = db.one("SELECT COUNT(*) n FROM positions WHERE opened_at>=?", (n,))["n"]
    lastpos = db.one("SELECT p.*, c.symbol FROM positions p LEFT JOIN coins c ON c.mint=p.mint ORDER BY p.id DESC LIMIT 1")
    lastexit = db.one("SELECT exit_reason FROM positions WHERE closed_at IS NOT NULL ORDER BY closed_at DESC LIMIT 1")
    opn = account.open_positions()
    eq = account.equity()
    def a(name, **kw):
        return {"name": name, "paused": db.paused(name), "heartbeat": hb.get(name), **kw}
    return [
        a("scanner", pools=pools, room=len(scanner.room),
          waiting_liq=sum(1 for e in scanner.room.values() if e.get("liq_log")),
          rockets=sum(1 for e in scanner.room.values() if e.get("rocket")),
          established_in_room=sum(1 for e in scanner.room.values() if e.get("source") == "established"),
          established=scanner.last_established, rows=[{"name": k["symbol"] or util.short(k["mint"]), "reason": k["reason"], "killed": k["verdict"] != "pass", "link": links.coin_url(k["mint"])} for k in kills]),
        a("auditor", taken=taken, rejected=rejected, enabled=s["auditor.enabled"], mint=last_audit["mint"] if last_audit else None,
          coin=name_of(last_audit["mint"]) if last_audit else None, layers=sorted(layers, key=lambda r: r["layer"])),
        a("analyst", score=v["score"] if v else None, coin=v["symbol"] if v else None, passed=bool(v["pass"]) if v else None,
          min_score=s["analyst.min_score"], mode=s["analyst.mode"]),
        a("executor", trades=trades, last=({"coin": lastpos["symbol"], "size": lastpos["size_usd"], "pct": round(lastpos["size_usd"] / eq * 100, 1) if eq else None, "ts": lastpos["opened_at"]} if lastpos else None),
          stack_pct=s["executor.stack_pct"]),
        a("risk", guarding=len(opn), last_exit=(lastexit or {}).get("exit_reason"), stop_pct=s["risk.stop_pct"], trail_pct=s["risk.trail_pct"],
          locked=bool(opn)),
    ]

# ---------- GET
@app.get("/api/state", dependencies=A)
async def state():
    eq = account.equity()
    start = night_start_balance()
    first = db.one("SELECT value FROM balance ORDER BY ts LIMIT 1")
    unread = db.one("SELECT COUNT(*) n FROM pushes WHERE seen=0")["n"]
    hb = db.one("SELECT MAX(ts) t FROM heartbeats")
    return {"mode": config.get("desk.mode"), "balance": round(eq, 2), "today_pct": round((eq / start - 1) * 100, 2) if start else 0,
            "multiplier": round(eq / start, 3) if start else 1.0, "free": round(account.free(), 2),
            "night_start": night_iso(), "agents": agents_summary(), "running": sum(1 for a in AGENTS if not db.paused(a)),
            "activity": act_rows(db.q("SELECT * FROM activity ORDER BY id DESC LIMIT 5")), "unread": unread,
            "positions": [{**p, "name": name_of(p["mint"]), "link": links.coin_url(p["mint"]), "last": account.last_price(p["mint"])} for p in account.open_positions()],
            "warning": config.ticket_check(), "updated": hb["t"] if hb else None, "server_time": util.iso()}

RANGES = {"LIVE": None, "1H": 1, "4H": 4, "1D": 24, "1W": 168, "ALL": 10**6}

@app.get("/api/chart", dependencies=A)
async def chart(range: str = "LIVE"):
    if range not in RANGES: raise HTTPException(400, "range must be LIVE|1H|4H|1D|1W|ALL")
    since = night_iso() if RANGES[range] is None else util.iso(util.now() - dt.timedelta(hours=min(RANGES[range], 24 * 3650)))
    pts = db.q("SELECT ts, value FROM balance WHERE ts>=? ORDER BY ts", (since,))
    if len(pts) > 600:
        step = len(pts) // 600 + 1
        pts = pts[::step] + [pts[-1]]
    marks = []
    for p in db.q("SELECT * FROM positions WHERE opened_at>=? OR closed_at>=?", (since, since)):
        if p["opened_at"] >= since:
            marks.append({"ts": p["opened_at"], "kind": "bought", "label": "Bought", "mint": p["mint"]})
        if p["closed_at"] and p["closed_at"] >= since:
            if p["exit_reason"] == "stop":
                marks.append({"ts": p["closed_at"], "kind": "stop", "label": f"-{risk_agent.stop_pct_of(p):g}% · -${abs(p['pnl_usd'] or 0):,.0f}", "mint": p["mint"]})
            else:
                marks.append({"ts": p["closed_at"], "kind": "win" if (p["pnl_usd"] or 0) >= 0 else "stop",
                              "label": f"{'+' if (p['pnl_usd'] or 0) >= 0 else '-'}${abs(p['pnl_usd'] or 0):,.0f}", "mint": p["mint"]})
    return {"range": range, "start": pts[0]["value"] if pts else None, "points": pts, "marks": marks}

@app.get("/api/activity", dependencies=A)
async def activity(before: int | None = None):
    rows = db.q("SELECT * FROM activity WHERE id<? ORDER BY id DESC LIMIT 30", (before,)) if before else db.q("SELECT * FROM activity ORDER BY id DESC LIMIT 30")
    return {"rows": act_rows(rows), "next": rows[-1]["id"] if len(rows) == 30 else None}

_viewed: dict[str, float] = {}

async def _fresh_price(mint):
    """api.py writes db.prices every 60s for coins viewed tonight (not in the room / not open)."""
    c = db.coin(mint) or {}
    if not c.get("pool") or time.time() - _viewed.get(mint, 0) < 60:
        return None
    _viewed[mint] = time.time()
    try:
        v = chain.pair_view((await S.dex_pairs([c["pool"]])).get(c["pool"]))
    except Exception:
        return None
    if v and v["price"] is not None:
        last = db.one("SELECT ts FROM prices WHERE mint=? ORDER BY ts DESC LIMIT 1", (mint,))
        if not last or (util.now() - util.parse(last["ts"])).total_seconds() >= 55:
            db.price(mint, v["price"], v["vol_m5"])
    return v

@app.get("/api/coin/{mint}", dependencies=A)
async def coin(mint: str):
    c = db.coin(mint)
    if not c: raise HTTPException(404, "unknown coin")
    v = await _fresh_price(mint)
    rows = db.q("SELECT ts, price, volume_m5 FROM prices WHERE mint=? AND ts>=? ORDER BY ts", (mint, util.iso(util.now() - dt.timedelta(hours=24))))
    candles, prev_vol = [], None
    for r in rows:
        k = r["ts"][:16]
        vol_d = max(0.0, (r["volume_m5"] or 0) - prev_vol) if prev_vol is not None else 0.0
        prev_vol = r["volume_m5"]
        if candles and candles[-1]["t"] == k:
            cd = candles[-1]; cd["h"] = max(cd["h"], r["price"]); cd["l"] = min(cd["l"], r["price"]); cd["c"] = r["price"]; cd["v"] += vol_d
        else:
            candles.append({"t": k, "o": r["price"], "h": r["price"], "l": r["price"], "c": r["price"], "v": vol_d})
    s = config.all_settings()
    p = db.one("SELECT * FROM positions WHERE mint=? ORDER BY id DESC LIMIT 1", (mint,))
    pos = None
    if p:
        last = account.last_price(mint) or p["entry_price"]
        pos = {**p, "stop_pct": risk_agent.stop_pct_of(p), "exit_line": risk_agent.exit_line(p, s) if not p["closed_at"] else None,
               "last": last, "unrealized": p["size_usd"] * (last / p["entry_price"] - 1) if not p["closed_at"] else None}
    return {"coin": c, "name": c.get("symbol") or c.get("name"), "link": links.coin_url(mint), "mode": config.get("desk.mode"),
            "candles": candles[-240:], "stats": {"mcap": v["mcap"], "liquidity": v["liquidity"], "vol24": v["vol_h24"], "holders": c.get("holders")} if v else
            {"mcap": None, "liquidity": None, "vol24": None, "holders": c.get("holders")}, "position": pos}

@app.get("/api/audit/{mint}", dependencies=A)
async def audit(mint: str):
    rows = db.q("SELECT * FROM audits WHERE mint=? ORDER BY id DESC LIMIT 8", (mint,))
    rows = sorted(rows, key=lambda r: r["layer"])
    red = next((r for r in rows if r["pass"] == 0), None)
    return {"mint": mint, "name": name_of(mint), "link": links.coin_url(mint), "layers": rows, "enabled": config.get("auditor.enabled"),
            "summary": (f"Rejected · {red['value_text']}" if red else (f"Cleared · {sum(1 for r in rows if r['pass'] == 1)}/8 parts" if rows else None))}

@app.get("/api/audits", dependencies=A)
async def audits_list():
    rows = db.q("SELECT mint, MAX(id) id FROM audits GROUP BY mint ORDER BY id DESC LIMIT 20")
    return {"rows": [{"mint": r["mint"], "name": name_of(r["mint"])} for r in rows]}

@app.get("/api/agents/{name}/decisions", dependencies=A)
async def decisions(name: str):
    if name not in AGENTS: raise HTTPException(404, "unknown agent")
    rows = db.q("SELECT * FROM decisions WHERE agent=? ORDER BY id DESC LIMIT 20", (name,))
    return {"agent": name, "paused": db.paused(name), "rows": [{**r, "time": util.local_hm(r["ts"]), "link": links.coin_url(r["mint"]) if r["mint"] else None} for r in rows]}

@app.get("/api/account", dependencies=A)
async def acct():
    return {"mode": config.get("desk.mode"), "live_locked": True, "stack": round(account.equity(), 2), "free": round(account.free(), 2),
            "paper_start_stack": config.get("desk.paper_start_stack"), "push_subs": db.one("SELECT COUNT(*) n FROM push_subs")["n"],
            "vapid_public": webpush.public_key(), "signup_url": links.SIGNUP_URL, "profile_url": links.profile_url(),
            "warning": config.ticket_check(), "venue": links.VENUE}

@app.get("/api/settings", dependencies=A)
async def get_settings():
    return {"settings": config.describe(), "change_log": db.q("SELECT * FROM change_log ORDER BY ts DESC LIMIT 20")}

@app.get("/api/pushes", dependencies=A)
async def pushes():
    return {"rows": db.q("SELECT id,ts,mint,kind,title,body,url,seen FROM pushes ORDER BY id DESC LIMIT 30")}

@app.get("/api/shadow", dependencies=A)
async def get_shadow(hours: float = 72, top: int = 15):
    """rejected coins re-read at +6h/+24h, per rule: rejected, >=1.5x / >=2x with liq >= $20K, died, top missed."""
    from . import shadow
    return shadow.summary(util.iso(util.now() - __import__("datetime").timedelta(hours=hours)), top)

@app.get("/api/experiments", dependencies=A)
async def get_experiments():
    """per experiment tag: coins that passed a stage because of the change, trades, PAPER PnL so far."""
    from . import tags
    return tags.experiments()

@app.get("/api/scanner/room", dependencies=A)
async def get_room():
    from .agents import scanner
    import time as _t
    return {"room": [{"mint": m, "name": name_of(m), "source": e.get("source"), "waited_min": round((_t.time() - e["t0"]) / 60, 1),
                      "first_liq": e.get("first_liq"), "peak": e.get("peak"), "rocket": bool(e.get("rocket")),
                      "waiting_on_liq": bool(e.get("liq_log"))} for m, e in scanner.room.items()],
            "established": scanner.last_established}

@app.get("/api/report", dependencies=A)
async def get_report():
    return Response(report.html(), media_type="text/html")

# ---------- POST
class SetBody(BaseModel):
    key: str | None = None
    value: object | None = None
    changes: dict | None = None

@app.post("/api/settings", dependencies=A)
async def post_settings(b: SetBody):
    ch = b.changes or ({b.key: b.value} if b.key else {})
    if not ch: raise HTTPException(400, "nothing to change")
    done = []
    for k, v in ch.items():
        try:
            done.append(config.set(k, v, "app"))
        except config.SettingError as e:
            return JSONResponse({"ok": False, "error": str(e), "done": [d[0] for d in done]}, status_code=422)
    return {"ok": True, "done": [{"key": k, "old": o, "new": n} for k, o, n in done], "warning": config.ticket_check()}

@app.post("/api/agents/{name}/{action}", dependencies=A)
async def pause(name: str, action: str):
    if name not in AGENTS or action not in ("pause", "resume"): raise HTTPException(404, "unknown")
    if action == "pause" and name == "risk" and account.open_positions():
        return JSONResponse({"ok": False, "error": "Risk can't be paused while a position is open"}, status_code=409)
    db.set_paused(name, action == "pause")
    return {"ok": True, "agent": name, "paused": action == "pause"}

class ModeBody(BaseModel):
    mode: str
    confirm: str | None = None

@app.post("/api/mode", dependencies=A)
async def mode(b: ModeBody):
    if b.mode.upper() == "LIVE":
        if b.confirm != "LIVE":
            return JSONResponse({"ok": False, "error": 'LIVE needs {"confirm":"LIVE"}'}, status_code=400)
        return JSONResponse({"ok": False, "error": "LIVE is locked. The desk runs PAPER only."}, status_code=403)
    return {"ok": True, "mode": "PAPER"}

class PushBody(BaseModel):
    endpoint: str
    keys: dict

@app.post("/api/push", dependencies=A)
async def push_sub(b: PushBody):
    if not b.endpoint.startswith("https://") or "p256dh" not in b.keys or "auth" not in b.keys:
        raise HTTPException(400, "bad subscription")
    db.x("INSERT INTO push_subs(endpoint,p256dh,auth,created_at) VALUES(?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET p256dh=excluded.p256dh, auth=excluded.auth",
         (b.endpoint, b.keys["p256dh"], b.keys["auth"], util.iso()))
    return {"ok": True, "subs": db.one("SELECT COUNT(*) n FROM push_subs")["n"]}

class TestPushBody(BaseModel):
    title: str = "Test push"
    body: str = "Desk is on. Tap to open pump.fun."

@app.post("/api/push/test", dependencies=A)
async def push_test(b: TestPushBody | None = None):
    b = b or TestPushBody()
    r = await webpush.push(b.title[:80], b.body[:200], None, "test", url=links.SIGNUP_URL)
    return {"ok": r["ok"] > 0, "subs": r["subs"], "delivered": r["ok"], "title": r["title"]}

@app.post("/api/pushes/seen", dependencies=A)
async def pushes_seen():
    db.x("UPDATE pushes SET seen=1 WHERE seen=0"); return {"ok": True}

@app.post("/api/skip/{mint}", dependencies=A)
async def skip(mint: str):
    commands.skip(mint); return {"ok": True}

class CmdBody(BaseModel):
    text: str

@app.post("/api/command", dependencies=A)
async def command(b: CmdBody):
    return await commands.arun(b.text, who="app")

# ---------- SSE
@app.get("/api/stream", dependencies=A)
async def stream(request: Request):
    q = bus.subscribe()
    async def gen():
        try:
            yield "retry: 3000\n\n"
            last_bal = time.time()
            while True:
                if await request.is_disconnected():
                    break
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15)
                    yield bus.sse(msg)
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
                if time.time() - last_bal > 15:
                    last_bal = time.time()
                    yield bus.sse({"id": 0, "event": "balance", "data": {"balance": round(account.equity(), 2), "ts": util.iso()}})
        finally:
            bus.unsubscribe(q)
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"x-accel-buffering": "no"})

# ---------- static app (public shell, no data)
@app.get("/")
async def index():
    return FileResponse(os.path.join(WEB, "index.html"), media_type="text/html")

@app.get("/sw.js")
async def sw():
    return FileResponse(os.path.join(WEB, "sw.js"), media_type="application/javascript", headers={"service-worker-allowed": "/"})

@app.get("/vapid.json")
async def vapid():
    return {"key": webpush.public_key()}   # public key only

app.mount("/", StaticFiles(directory=WEB), name="web")
