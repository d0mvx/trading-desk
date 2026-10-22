#!/usr/bin/env python3
"""Publish ~/.desk/dashboard (index.html, data.json, charts.json, apple-touch-icon.png ONLY) to a private here.now Site.
First run creates the Site + sets the visitor password; later runs PUT a new version listing all 3 files with
sha256 hashes so here.now skips unchanged bytes. index.html is refreshed at most every 30 min (the page pulls fresh
numbers from data.json); data.json goes up every run when it changed. Logs: ~/.desk/logs/herenow.log"""
import os, sys, json, time, fcntl, hashlib, secrets, shutil, datetime as dt, requests
from zoneinfo import ZoneInfo
DESK = os.path.expanduser("~/.desk"); BER = ZoneInfo("Europe/Berlin")
API = "https://here.now"; STATE = f"{DESK}/herenow_site.json"; STAGE = f"{DESK}/.herenow_stage"
FILES = [("index.html", "text/html; charset=utf-8"), ("data.json", "application/json; charset=utf-8"), ("charts.json", "application/json; charset=utf-8"), ("apple-touch-icon.png", "image/png"), ("v.json", "application/json; charset=utf-8")]   # charts.json: tap-to-expand position charts (2026-10-20)
INDEX_EVERY_S = 1800
DISPLAY = "Grok Bot Trading Desk"

def log(msg):
    with open(f"{DESK}/logs/herenow.log", "a") as f: f.write(f"{dt.datetime.now(BER):%Y-%m-%d %H:%M:%S %Z} {msg}\n")

def key():
    if os.environ.get("HERENOW_API_KEY", "").strip(): return os.environ["HERENOW_API_KEY"].strip()   # 2026-10-22 github: env first
    for l in open(os.path.expanduser("~/.herenow/credentials")):
        if l.startswith("HERENOW_API_KEY="): return l.split("=", 1)[1].strip()
    raise SystemExit("no key")

def H(extra=None):
    h = {"Authorization": f"Bearer {key()}", "X-HereNow-Client": "cursor/direct-api"}
    if extra: h.update(extra)
    return h

def call(method, path, body=None):
    r = requests.request(method, API + path, headers=H({"content-type": "application/json"}), json=body, timeout=90)
    if r.status_code == 429 or (r.status_code >= 400 and "rate_limit" in r.text):
        ra = r.headers.get("Retry-After") or (r.json().get("retry_after") if r.headers.get("content-type", "").startswith("application/json") else None)
        raise RateLimited(int(float(ra or 60)))
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
    return r.json(), r.headers

class RateLimited(Exception): pass

ENV_STATE = {"slug": "HERENOW_SITE_SLUG", "password": "HERENOW_SITE_PASSWORD", "widget_slug": "HERENOW_WIDGET_SLUG", "widget_path": "HERENOW_WIDGET_PATH"}
def load_state():
    try: st = json.load(open(STATE))
    except FileNotFoundError: st = {}
    for k, e in ENV_STATE.items():   # 2026-10-22 github: site identity from env (Actions secrets) when the local file lacks it
        if not st.get(k) and os.environ.get(e, "").strip(): st[k] = os.environ[e].strip()
    return st
def save_state(s):
    old = os.umask(0o077); tmp = STATE + ".tmp"
    json.dump(s, open(tmp, "w"), indent=1); os.replace(tmp, STATE); os.chmod(STATE, 0o600); os.umask(old)

WORDS = ("amber anchor apple arrow atlas autumn badge bamboo banjo beacon birch bison blossom bonfire breeze brick bridge "
         "bronze cabin cactus candle canyon carbon castle cedar cherry cinder citrus cliff clover cobalt comet copper coral "
         "cosmic cotton crater crimson crystal cypress dagger delta desert dolphin dragon drift eagle echo ember emerald "
         "falcon fern fiddle flint forest fossil fox frost galaxy garnet geyser ginger glacier granite gravel harbor hazel "
         "heron hollow honey horizon iris island ivory jade jasper jungle kayak kernel kettle lagoon lantern lava lemon "
         "lilac lotus lunar magnet mango maple marble meadow meteor mint mirror monsoon mosaic nectar nickel nimbus oasis "
         "ocean olive onyx orbit orchid otter oyster palm panda pebble pepper pine planet plum polar poppy prism pumpkin "
         "quartz quill radar raven reef ripple river rocket ruby saffron salmon sapphire satin shadow sierra silver sky "
         "slate sonar spruce squid summit sunset tango thistle thunder tiger timber topaz torch tulip tundra velvet "
         "violet volcano walnut willow winter zebra zephyr").split()

def gen_password():
    w = [secrets.choice(WORDS) for _ in range(3)]
    return "-".join(w) + "-" + f"{secrets.randbelow(10000):04d}"

def sha(path): return hashlib.sha256(open(path, "rb").read()).hexdigest()

def ui_of(path):
    try:
        head = open(path, encoding="utf-8", errors="ignore").read(4000); i = head.find('name="desk-ui" content="')
        return head[i + 24:i + 36] if i >= 0 else None
    except Exception: return None

def stage(st, force_index):
    os.makedirs(STAGE, exist_ok=True)
    src = f"{DESK}/dashboard"
    shutil.copy(f"{src}/data.json", f"{STAGE}/data.json")
    if os.path.exists(f"{src}/charts.json"): shutil.copy(f"{src}/charts.json", f"{STAGE}/charts.json")
    elif not os.path.exists(f"{STAGE}/charts.json"): open(f"{STAGE}/charts.json", "w").write("{}")
    shutil.copy(f"{src}/apple-touch-icon.png", f"{STAGE}/apple-touch-icon.png")
    # SAVIP live: tiny version file next to data.json (same publish, no extra version): the page polls this ~80-byte file every 10 s
    # and downloads data.json only when it changed. here.now answers no 304s, so this is what keeps mobile data use low.
    try: g = json.load(open(f"{STAGE}/data.json")).get("generated_ts")
    except Exception: g = None
    open(f"{STAGE}/v.json", "w").write(json.dumps({"g": g, "ui": ui_of(f"{src}/index.html")}))
    # page code changed (CSS/JS/scene hash in <meta name="desk-ui">) -> upload index.html now instead of waiting up to 30 min
    if not force_index and os.path.exists(f"{STAGE}/index.html") and ui_of(f"{src}/index.html") != ui_of(f"{STAGE}/index.html"): force_index = True
    if force_index or not os.path.exists(f"{STAGE}/index.html") or time.time() - st.get("index_uploaded_ts", 0) >= INDEX_EVERY_S:
        shutil.copy(f"{src}/index.html", f"{STAGE}/index.html"); return True
    return False

def stage_logos():
    """SAVIP v2 (2026-10-21): coin/stock logos (64px WebP, built by dash_logos.py) served next to index.html. Capped count/bytes."""
    src, dst = f"{DESK}/dashboard/logos", f"{STAGE}/logos"; out = []
    try:
        os.makedirs(dst, exist_ok=True)
        want = sorted((f for f in os.listdir(src) if f.endswith(".webp")), key=lambda f: -os.path.getmtime(f"{src}/{f}"))[:150] if os.path.isdir(src) else []
        total = 0
        for f in want:
            n = os.path.getsize(f"{src}/{f}")
            if n > 60_000 or total + n > 1_000_000: continue
            total += n; shutil.copy(f"{src}/{f}", f"{dst}/{f}"); out.append((f"logos/{f}", "image/webp"))
        keep = {p.split("/", 1)[1] for p, _ in out}
        for f in os.listdir(dst):
            if f not in keep: os.remove(f"{dst}/{f}")
    except Exception as e:
        log(f"[PUBLISH] logos skipped: {type(e).__name__}: {str(e)[:120]}"); return []
    return sorted(out)

def upload_and_finalize(slug, resp):
    up = resp["upload"]; n = 0
    for u in up["uploads"]:
        with open(f"{STAGE}/{u['path']}", "rb") as f:
            r = requests.put(u["url"], data=f.read(), headers=u.get("headers") or {}, timeout=60)
        if r.status_code >= 300: raise RuntimeError(f"upload {u['path']} -> {r.status_code} {r.text[:200]}")
        n += 1
    fin, _ = call("POST", f"/api/v1/publish/{slug}/finalize", {"versionId": up["versionId"]})
    return fin, n, up.get("skipped") or []

def ensure_password(st):
    """Persist the password BEFORE sending it, then PATCH; verify access mode is 'password'."""
    if not st.get("password"):
        st["password"] = gen_password(); save_state(st)
    call("PATCH", f"/api/v1/publish/{st['slug']}/metadata", {"password": st["password"], "displayName": DISPLAY})
    acc, _ = call("GET", f"/api/v1/publish/{st['slug']}/access")
    mode = (acc.get("access") or {}).get("mode")
    st["password_set"] = mode == "password"; st["access_mode"] = mode; save_state(st)
    log(f"[PUBLISH] access mode now {mode}")

def main():
    lock = open(f"{DESK}/.herenow.lock", "w")
    try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError: return
    st = load_state()
    if os.environ.get("HERENOW_REQUIRE_SLUG") and not st.get("slug"):   # github: never create a second site from a runner
        log("[PUBLISH] skipped: HERENOW_REQUIRE_SLUG set but no site slug configured"); return
    if time.time() < st.get("retry_after_ts", 0):
        log(f"[PUBLISH] waiting for rate limit until {dt.datetime.fromtimestamp(st['retry_after_ts'], BER):%H:%M:%S}"); return
    if st.get("slug") and not st.get("password_set"):
        try: ensure_password(st)
        except Exception as e:
            log(f"[PUBLISH] ERROR setting password: {str(e)[:200]} (retry next run)"); st["last_error"] = str(e)[:300]; save_state(st); return
    new_index = stage(st, force_index="--full" in sys.argv)
    manifest = [{"path": p, "size": os.path.getsize(f"{STAGE}/{p}"), "contentType": ct, "hash": sha(f"{STAGE}/{p}")} for p, ct in FILES + stage_logos()]
    hashes = {m["path"]: m["hash"] for m in manifest}
    if st.get("slug") and hashes == st.get("hashes") and "--full" not in sys.argv:
        return   # nothing changed -> no publish (saves rate limit)
    try:
        if not st.get("slug"):
            resp, hdr = call("POST", "/api/v1/publish", {"files": manifest, "displayName": DISPLAY,
                              "displayDescription": "Private live dashboard (paper trading, virtual $100 desk)."})
            slug = resp["slug"]; st.update({"slug": slug, "created_at": dt.datetime.now(BER).isoformat(timespec="seconds")})
            save_state(st)
            fin, n, skipped = upload_and_finalize(slug, resp)
            st["siteUrl"] = fin.get("siteUrl") or resp.get("siteUrl"); save_state(st)
            log(f"[PUBLISH] created site {slug}, uploaded {n} files")
            ensure_password(st)
        else:
            slug = st["slug"]
            resp, hdr = call("PUT", f"/api/v1/publish/{slug}", {"files": manifest})
            fin, n, skipped = upload_and_finalize(slug, resp)
            if fin.get("siteUrl"): st["siteUrl"] = fin["siteUrl"]
            _up = [u['path'] for u in resp['upload']['uploads']]; _nl = sum(1 for x in _up if x.startswith("logos/"))
            log(f"[PUBLISH] {slug}: uploaded {n} ({', '.join([x for x in _up if not x.startswith('logos/')] + ([f'{_nl} logos'] if _nl else [])) or 'none'}), skipped {len(skipped)}")
        rl = {k: v for k, v in hdr.items() if "ratelimit" in k.lower()}
        if rl: st["ratelimit_headers"] = rl
        st["hashes"] = hashes; st["last_publish"] = dt.datetime.now(BER).isoformat(timespec="seconds")
        st["publishes"] = st.get("publishes", 0) + 1; st.pop("retry_after_ts", None); st["last_error"] = None
        if new_index: st["index_uploaded_ts"] = time.time()
        save_state(st)
    except RateLimited as e:
        st["retry_after_ts"] = time.time() + e.args[0]; st["last_error"] = f"rate limited {e.args[0]}s"; save_state(st)
        log(f"[PUBLISH] rate limited, retry after {e.args[0]}s")
    except Exception as e:
        st["last_error"] = str(e)[:300]; save_state(st)
        log(f"[PUBLISH] ERROR {type(e).__name__}: {str(e)[:300]} (will retry next run)")

WIDGET_EVERY_S = 300
WSTAGE = f"{DESK}/.herenow_widget_stage"
PLACEHOLDER = "<!doctype html><title>.</title><meta name=robots content=noindex>"

def publish_widget(st):
    """Separate PUBLIC Site holding only widget.json under an unguessable path (+ an empty index so there is no
    listing). Numbers only: balance, P&L, open count, last trade, meme dial, updated_at. Every 5 min."""
    if time.time() - st.get("widget_last_ts", 0) < WIDGET_EVERY_S: return
    if not st.get("widget_path"): st["widget_path"] = secrets.token_hex(16); save_state(st)
    os.makedirs(f"{WSTAGE}/{st['widget_path']}", exist_ok=True)
    shutil.copy(f"{DESK}/dashboard/widget.json", f"{WSTAGE}/{st['widget_path']}/widget.json")
    open(f"{WSTAGE}/index.html", "w").write(PLACEHOLDER)
    files = [("index.html", "text/html; charset=utf-8"), (f"{st['widget_path']}/widget.json", "application/json; charset=utf-8")]
    manifest = [{"path": p, "size": os.path.getsize(f"{WSTAGE}/{p}"), "contentType": ct, "hash": sha(f"{WSTAGE}/{p}")} for p, ct in files]
    if not st.get("widget_slug"):
        resp, _ = call("POST", "/api/v1/publish", {"files": manifest, "displayName": "Grok Bot widget feed",
                        "displayDescription": "Public numbers-only feed for the iOS widget."})
        st["widget_slug"] = resp["slug"]; save_state(st)
    else:
        resp, _ = call("PUT", f"/api/v1/publish/{st['widget_slug']}", {"files": manifest})
    up = resp["upload"]
    for u in up["uploads"]:
        r = requests.put(u["url"], data=open(f"{WSTAGE}/{u['path']}", "rb").read(), headers=u.get("headers") or {}, timeout=60)
        if r.status_code >= 300: raise RuntimeError(f"widget upload {u['path']} -> {r.status_code}")
    fin, _ = call("POST", f"/api/v1/publish/{st['widget_slug']}/finalize", {"versionId": up["versionId"]})
    base = fin.get("siteUrl") or resp.get("siteUrl") or st.get("widget_site_url")
    st["widget_site_url"] = base; st["widget_url"] = base.rstrip("/") + f"/{st['widget_path']}/widget.json"
    st["widget_last_ts"] = time.time(); save_state(st)
    log(f"[PUBLISH] widget feed {st['widget_slug']} updated")

if __name__ == "__main__":
    main()
    st = load_state()
    if st.get("password_set") and time.time() >= st.get("retry_after_ts", 0):
        try: publish_widget(st)
        except RateLimited as e:
            st["retry_after_ts"] = time.time() + e.args[0]; save_state(st); log(f"[PUBLISH] widget rate limited {e.args[0]}s")
        except Exception as e:
            log(f"[PUBLISH] widget ERROR {type(e).__name__}: {str(e)[:200]}")
