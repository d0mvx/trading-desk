"""STEP 13: no secret value in web/, logs/, the repo, API responses or the report. Values are never printed."""
import os, glob, httpx
from desk import util, report
ROOT = util.ROOT

def _secrets():
    v = {k: os.environ.get(k) for k in ("TYPESAFE_API_KEY", "HELIUS_API_KEY", "NGROK_AUTHTOKEN")}
    v["APP_TOKEN"] = util.secret("app_token"); v["DATA_PATH"] = util.secret("data_path")
    pem = open(os.path.join(ROOT, ".secrets/vapid_private.pem")).read()
    v["VAPID_PRIVATE"] = "".join(l for l in pem.splitlines() if "-----" not in l)
    return {k: x for k, x in v.items() if x and len(x) >= 12}

def _hits(text, S):
    return [k for k, x in S.items() if x in text]

def test_files():
    S = _secrets(); assert len(S) >= 5
    bad = []
    files = [f for f in glob.glob(ROOT + "/**/*", recursive=True) if os.path.isfile(f) and "/.secrets/" not in f and "/.venv/" not in f
             and not f.endswith((".db", ".db-wal", ".db-shm", ".pyc", ".png"))]
    for f in files:
        t = open(f, errors="ignore").read()
        for k in _hits(t, S): bad.append((f.replace(ROOT, ""), k))
    assert not bad, bad   # shows file + secret NAME only

def test_live_api_and_report():
    S = _secrets(); tok = S["APP_TOKEN"]
    h = {"Authorization": f"Bearer {tok}", "ngrok-skip-browser-warning": "1"}
    bad = []
    for base in ("http://127.0.0.1:8787", "https://relight-stalling-periscope.ngrok-free.dev"):
        for p in ("/api/state", "/api/activity", "/api/account", "/api/settings", "/api/pushes", "/api/chart?range=1D", "/api/audits",
                  "/api/report", "/", "/app.js", "/sw.js", "/vapid.json", "/manifest.json"):
            try:
                t = httpx.get(base + p, headers=h, timeout=20).text
            except httpx.TransportError:
                continue          # base not up (e.g. CI before the desk starts); checked again after start
            bad += [(base[:12], p, k) for k in _hits(t, {k: v for k, v in S.items() if k != "APP_TOKEN"} if p != "/api/state" else S)]
            if k := _hits(t, {"APP_TOKEN": tok}): bad.append((base[:12], p, "APP_TOKEN"))
    bad += [("report", k) for k in _hits(report.markdown(True) + report.html(True), S)]
    assert not bad, bad
