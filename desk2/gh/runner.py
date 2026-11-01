"""desk2 on GitHub Actions: one long job (~5h50m) per run, chained by self-dispatch. PAPER only.

Roles
  successor : another desk run (or the box, pred=box) is live -> request the handoff, wait until the
              predecessor has stopped desk+ngrok and pushed the final state, then start.
  fresh     : nothing live -> start from the latest state.
  noop      : scheduled safety-net run while a desk run is live -> exit.

Handoff (keeps the ngrok domain single-owner, gap = stop -> successor's public URL answers):
  successor  push refs/heads/handoff-desk2  {succ, pred}
  pred       sees it (poll 5 s), stops ngrok+desk, snapshot+encrypt, force-push `state-desk2` with meta.released_for=succ
  successor  polls `state` every 2 s, imports, starts desk+ngrok, measures the gap.
"""
from __future__ import annotations
import argparse, json, os, signal, subprocess, sys, time, datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://relight-stalling-periscope.ngrok-free.dev"
PY = sys.executable
STATE_REF, REQ_REF, WF = "state-desk2", "handoff-desk2", "desk2.yml"   # never the old desk's `state` branch
STOP = False

def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)

def sh(*cmd, check=True, capture=True, cwd=ROOT, input=None):
    r = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, input=input)
    if check and r.returncode:
        raise RuntimeError(f"{cmd[0]} {cmd[1] if len(cmd) > 1 else ''} failed rc={r.returncode}: {(r.stderr or '')[-300:]}")
    return (r.stdout or "").strip()

# ---------- git refs on origin (no working-tree changes) ----------
def remote_sha(ref: str) -> str | None:
    out = sh("git", "ls-remote", "origin", f"refs/heads/{ref}", check=False)
    return out.split()[0] if out else None

def fetch_file(ref: str, path: str) -> bytes | None:
    if subprocess.run(["git", "fetch", "-q", "--depth", "1", "origin", f"+refs/heads/{ref}:refs/remotes/origin/{ref}"],
                      cwd=ROOT, capture_output=True).returncode:
        return None
    r = subprocess.run(["git", "show", f"refs/remotes/origin/{ref}:{path}"], cwd=ROOT, capture_output=True)
    return r.stdout if r.returncode == 0 else None

def push_files(ref: str, files: dict[str, bytes], msg: str, lease: str | None = "auto", retries=6) -> str:
    """one orphan commit holding `files`, force-pushed to ref (lease = expected current sha)."""
    entries = []
    for name, data in files.items():
        sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], cwd=ROOT, input=data, capture_output=True, check=True).stdout.decode().strip()
        entries.append(f"100644 blob {sha}\t{name}")
    tree = sh("git", "mktree", input="\n".join(entries) + "\n")
    env = dict(os.environ, GIT_AUTHOR_NAME="desk-bot", GIT_COMMITTER_NAME="desk-bot",
               GIT_AUTHOR_EMAIL="41898282+github-actions[bot]@users.noreply.github.com",
               GIT_COMMITTER_EMAIL="41898282+github-actions[bot]@users.noreply.github.com")
    commit = subprocess.run(["git", "commit-tree", tree, "-m", msg], cwd=ROOT, env=env, text=True,
                            capture_output=True, check=True).stdout.strip()
    for i in range(retries):
        cur = remote_sha(ref) if lease == "auto" else lease
        lease_arg = f"--force-with-lease=refs/heads/{ref}:{cur or ''}"
        r = subprocess.run(["git", "push", "-q", lease_arg, "origin", f"{commit}:refs/heads/{ref}"], cwd=ROOT,
                           capture_output=True, text=True)
        if r.returncode == 0:
            return commit
        log(f"push {ref} failed (try {i+1}): {r.stderr.strip()[-200:]}")
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"push {ref} failed")

# ---------- state ----------
def save_state(owner: str, released_for: str | None = None, stopped_at: float | None = None, note="checkpoint") -> dict:
    out = os.path.join(ROOT, "state.enc")
    sh(PY, "gh/state.py", "export", ROOT, out)
    blob = open(out, "rb").read()
    import hashlib
    meta = {"saved_at": time.time(), "saved_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "owner": owner, "released_for": released_for, "stopped_at": stopped_at, "note": note,
            "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest()}
    push_files(STATE_REF, {"state.enc": blob, "meta.json": json.dumps(meta, indent=1).encode(),
                         "README.md": b"Encrypted desk2 state (AES-256-GCM, key in GitHub secret DESK_STATE_KEY). See desk2/gh/state.py on main.\n"},
               f"state {meta['saved_at_utc']} {owner} {note}")
    log(f"state saved ({note}, {len(blob)} bytes, released_for={released_for})")
    return meta

def load_state() -> dict | None:
    meta = fetch_file(STATE_REF, "meta.json")
    blob = fetch_file(STATE_REF, "state.enc")
    if not blob:
        log("no state on branch -> starting empty"); return None
    p = os.path.join(ROOT, "state.enc"); open(p, "wb").write(blob)
    sh(PY, "gh/state.py", "import", p, ROOT)
    return json.loads(meta) if meta else {}

# ---------- processes ----------
PROCS: dict[str, subprocess.Popen] = {}

def start_desk():
    os.makedirs(os.path.join(ROOT, "logs"), exist_ok=True)
    for name in ("desk", "ngrok"):
        PROCS[name] = subprocess.Popen(["bash", f"gh/{name}_supervisor.sh"], cwd=ROOT, start_new_session=True,
                                       stdout=open(os.path.join(ROOT, f"logs/{name}_super.out"), "a"), stderr=subprocess.STDOUT)
    log("desk + ngrok supervisors started")

def stop_desk():
    for name in ("ngrok", "desk"):                      # ngrok first: release the domain
        p = PROCS.pop(name, None)
        if p and p.poll() is None:
            try: os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError: pass
    t = time.time()
    while time.time() - t < 6 and subprocess.run(["pgrep", "-f", "desk.main|ngrok http"], capture_output=True).returncode == 0:
        time.sleep(0.3)
    subprocess.run(["pkill", "-9", "-f", "desk.main|ngrok http"], capture_output=True)
    log("desk + ngrok stopped")

def public_ok() -> bool:
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{content_type}", "-m", "8",
                        "-H", "ngrok-skip-browser-warning: 1", URL + "/manifest.json"], capture_output=True, text=True)
    return r.stdout.startswith("200 application/json")

def wait_public(t0: float, limit=180) -> float | None:
    while time.time() - t0 < limit:
        if public_ok() and subprocess.run(["curl", "-s", "-m", "3", "http://127.0.0.1:8787/manifest.json"],
                                          capture_output=True).returncode == 0:
            return time.time()
        time.sleep(0.5)
    return None

# ---------- github runs ----------
def gh_json(*a):
    return json.loads(sh("gh", *a) or "null")

def live_runs(me: str) -> list[str]:
    runs = gh_json("run", "list", "--workflow", WF, "--status", "in_progress", "--json", "databaseId", "--limit", "20")
    return [str(r["databaseId"]) for r in runs if str(r["databaseId"]) != me]

def run_done(rid: str) -> bool:
    try:
        return gh_json("run", "view", rid, "--json", "status")["status"] == "completed"
    except Exception:
        return False

def summary(md: str):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p: open(p, "a").write(md + "\n")

# ---------- main ----------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--me", required=True); ap.add_argument("--slot", default="s")
    ap.add_argument("--pred", default=""); ap.add_argument("--event", default="workflow_dispatch")
    ap.add_argument("--job-start", type=float, default=time.time())
    ap.add_argument("--handover-min", type=float, default=332); ap.add_argument("--end-min", type=float, default=348)
    ap.add_argument("--role-only", action="store_true")
    a = ap.parse_args()
    me = a.me

    live = live_runs(me)
    pred = a.pred or (live[0] if live else "")
    if a.role_only:
        role = "noop" if (a.event == "schedule" and live) else ("successor" if pred else "fresh")
        print(role); return
    if a.event == "schedule" and live:
        log("safety net: desk already live in run(s)", live, "-> noop"); return

    def on_sig(*_):
        global STOP; STOP = True
    signal.signal(signal.SIGTERM, on_sig); signal.signal(signal.SIGINT, on_sig)

    stopped_at = None
    if pred:
        log(f"successor of {pred}: requesting handoff")
        push_files(REQ_REF, {"req.json": json.dumps({"succ": me, "pred": pred, "at": time.time()}).encode()},
                   f"handoff {pred} -> {me}")
        t0, last, meta = time.time(), None, None
        while True:
            if STOP: log("cancelled while waiting"); return
            sha = remote_sha(STATE_REF)
            if sha and sha != last:
                last = sha
                m = fetch_file(STATE_REF, "meta.json")
                meta = json.loads(m) if m else {}
                if meta.get("released_for") == me:
                    stopped_at = meta.get("stopped_at"); log("predecessor released the desk"); break
            if pred != "box" and int(time.time() - t0) % 15 < 2 and run_done(pred):
                log("predecessor run finished without releasing -> take latest state"); break
            if time.time() - t0 > 25 * 60:
                raise SystemExit("predecessor never released within 25 min -> not starting (no double desk)")
            time.sleep(2)
    meta = load_state()
    if stopped_at is None and meta:
        stopped_at = meta.get("stopped_at")
    t_start = time.time()
    start_desk()
    t_up = wait_public(t_start)
    if t_up is None:
        log("::warning::public URL not answering after 180 s (desk keeps trying)")
    gap = (t_up - stopped_at) if (t_up and stopped_at) else None
    log(f"desk live; public URL ok={t_up is not None}; handoff gap={'%.1f s' % gap if gap else 'n/a'}")
    summary(f"### desk2 run {me}\n- role: {'successor of ' + pred if pred else 'fresh'}\n- handoff gap (pred stop -> public URL 200): "
            f"{'%.1f s' % gap if gap else 'n/a'}\n")
    open(os.path.join(ROOT, "logs/handoff.log"), "a").write(json.dumps({"run": me, "pred": pred, "stopped_at": stopped_at,
                                                                       "up_at": t_up, "gap_s": gap}) + "\n")
    save_state(me, note="started")

    end = a.job_start + a.end_min * 60
    handover_at = a.job_start + a.handover_min * 60
    dispatched, last_ck, last_req = False, time.time(), remote_sha(REQ_REF)
    other = {"a": "b", "b": "a"}.get(a.slot, "a")
    while not STOP:
        now = time.time()
        if now >= end:
            log("planned end reached"); break
        if not dispatched and now >= handover_at:
            sh("gh", "workflow", "run", WF, "--ref", "main", "-f", f"slot={other}", "-f", f"pred={me}", check=False)
            dispatched = True; log(f"successor dispatched (slot {other})")
        sha = remote_sha(REQ_REF)
        if sha and sha != last_req:
            last_req = sha
            req = json.loads(fetch_file(REQ_REF, "req.json") or b"{}")
            if req.get("pred") == me and req.get("succ"):
                log(f"handoff requested by {req['succ']}")
                stop_desk(); t = time.time()
                save_state(me, released_for=req["succ"], stopped_at=t, note="handoff")
                open(os.path.join(ROOT, ".released"), "w").write(req["succ"])
                summary(f"- handed off to run {req['succ']} (save+push took {time.time() - t:.1f} s)\n")
                return
        if now - last_ck >= 300:
            try: save_state(me)
            except Exception as e: log("checkpoint failed:", e)
            last_ck = now
        time.sleep(5)
    stop_desk()
    save_state(me, released_for="any", stopped_at=time.time(), note="end" if not STOP else "cancel")
    open(os.path.join(ROOT, ".released"), "w").write("any")

if __name__ == "__main__":
    main()
