"""STEP 13: every pump.fun link is coin_url(mint) or SIGNUP_URL; no shorteners; unknown chain -> SIGNUP_URL."""
import os, re, json, subprocess
from fastapi.testclient import TestClient
from desk import links, db, util, webpush, report
from .conftest import arun
M = "6m7frLtvpHUNRfBHQHjtZZs812kVwKsY16gxPj6vpump"
URL_RE = re.compile(r"https?://[^\s\"'<>)`\]]+")
SHORT = ("bit.ly", "t.co/", "tinyurl", "goo.gl", "ow.ly", "is.gd", "rebrand.ly", "fomo.", "telegram", "t.me/")
OK_DOCS = {"https://pump.fun/docs/fees"}   # fees.py citation, not a button

def ok_link(u, mint=None):
    return u == links.SIGNUP_URL or u in OK_DOCS or bool(re.fullmatch(r"https://pump\.fun/coin/[1-9A-HJ-NP-Za-km-z]{32,44}", u))

def test_coin_url_rules():
    assert links.coin_url(M) == f"https://pump.fun/coin/{M}"
    assert links.coin_url(M, "ethereum") == links.SIGNUP_URL
    assert links.coin_url("not-a-mint") == links.SIGNUP_URL
    assert links.SIGNUP_URL == "https://pump.fun"

def test_repo_grep():
    root = os.path.join(util.ROOT, "desk")
    bad = []
    for d, _, fs in os.walk(root):
        if "/tests" in d or "__pycache__" in d: continue
        for f in fs:
            if not f.endswith((".py", ".js", ".html", ".json", ".css")): continue
            t = open(os.path.join(d, f), errors="ignore").read()
            for u in URL_RE.findall(t):
                u = u.rstrip(".,;")
                if any(s in u.lower() for s in SHORT): bad.append((f, u))
                if "pump.fun" in u and "{" not in u and not ok_link(u): bad.append((f, u))
    assert not bad, bad

def _seed():
    db.upsert_coin(M, name="Donald", symbol="DON", pool="PooL1111111111111111111111111111111111111", migrated_at=util.iso())
    db.activity("bought", M, "Executor", "Bought DON", "Executor · now", "$16.00")
    db.x("INSERT INTO positions(mint,opened_at,entry_price,size_usd,peak_price,stop_price,trail_active,fees_usd,mode) VALUES(?,?,?,?,?,?,?,?,?)",
         (M, util.iso(), 1.0, 16, 1.0, 0.94, 0, 0.2, "PAPER"))
    db.price(M, 1.01, 10)

def _walk(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items(): yield from _walk(v, path + "." + k)
    elif isinstance(o, list):
        for v in o: yield from _walk(v, path)
    elif isinstance(o, str):
        for u in URL_RE.findall(o): yield path, u

def test_api_push_account_report(tdb, sent):
    _seed()
    from desk.api import app
    tok = util.secret("app_token")
    c = TestClient(app); h = {"Authorization": f"Bearer {tok}"}
    seen = []
    for p in ("/api/state", "/api/activity", f"/api/coin/{M}", f"/api/audit/{M}", "/api/account", "/api/pushes", "/api/chart?range=1D"):
        r = c.get(p, headers=h); assert r.status_code == 200, p
        seen += [(p + k, u) for k, u in _walk(r.json()) if "pump.fun" in u]
    assert seen, "no links in API responses"
    assert all(ok_link(u) for _, u in seen), seen
    assert c.get(f"/api/coin/{M}", headers=h).json()["link"] == links.coin_url(M)
    acc = c.get("/api/account", headers=h).json()
    assert acc["signup_url"] == links.SIGNUP_URL
    res = arun(webpush.push("Buy DON · $16.00", "Auditor 8/8", M, "buy"))
    assert sent[-1]["url"] == links.coin_url(M) and sent[-1]["title"].startswith("PAPER · ")
    md = report.markdown(current=True)
    us = [u.rstrip(".,;") for u in URL_RE.findall(md)]
    assert links.coin_url(M) in us and links.SIGNUP_URL in us and all(ok_link(u) for u in us if "pump.fun" in u)
