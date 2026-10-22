#!/usr/bin/env python3
"""State transport between a live desk dir and a checkout of branch `state` (used on the GitHub runner AND on the box).
  export DESK WORKTREE          copy allowlisted state (deploy/state_manifest.txt) desk -> worktree; validates JSON, trims a
                                torn last line of .jsonl/.csv/.log; files in scope that vanished from the desk (e.g. STOP_ALL
                                removed, rejects rotated away) are deleted in the worktree
  import WORKTREE DESK [--index F]  copy worktree -> desk; deletes in DESK only files listed in the previous index F
  commit WORKTREE -m MSG [--push] [--retries N]   secret-scan, git add -A, commit if changed, push (rebase -X theirs on conflict)
Never prints file contents. Exit code != 0 only on push failure after all retries."""
import os, sys, json, time, shutil, argparse, subprocess, filecmp, fnmatch
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "deploy")); import deskfiles

def log(m): print(f"{time.strftime('%Y-%m-%d %H:%M:%S %Z')} [STATE] {m}", flush=True)

def scope_rules():
    rules = [l.strip() for l in open(os.path.join(deskfiles.HERE, "state_manifest.txt")) if l.strip() and not l.startswith("#")]
    return [r for r in rules if not r.startswith("!")], [r[1:] for r in rules if r.startswith("!")]

def in_scope(rel):
    inc, exc = scope_rules()
    return any(fnmatch.fnmatch(rel, p) for p in inc) and not any(fnmatch.fnmatch(rel, p) for p in exc) and not deskfiles.denied(rel)

def safe_copy(sp, dp):
    """Copy a file that may be mid-write. JSON must parse (retry 3x, else keep old copy); line files trimmed to last newline."""
    for attempt in range(3):
        b = open(sp, "rb").read()
        if sp.endswith(".json"):
            try: json.loads(b.decode("utf-8") or "null"); break
            except ValueError: time.sleep(0.4); continue
        else: break
    else:
        log(f"skip (invalid JSON after 3 reads): {os.path.basename(sp)}"); return False
    if sp.endswith((".jsonl", ".csv", ".log")) and b and not b.endswith(b"\n"):
        b = b[: b.rfind(b"\n") + 1]
    if os.path.exists(dp) and open(dp, "rb").read() == b: return False
    os.makedirs(os.path.dirname(dp), exist_ok=True); tmp = dp + ".sync-tmp"
    open(tmp, "wb").write(b); shutil.copystat(sp, tmp); os.replace(tmp, dp); return True

def export(desk, wt):
    files = deskfiles.resolve("state", desk); have = {s for s, _ in files}; n = d = 0
    for s, _ in files: n += safe_copy(os.path.join(desk, s), os.path.join(wt, s))
    for r, ds, fs in os.walk(wt):
        ds[:] = [x for x in ds if x != ".git"]
        for f in fs:
            rel = os.path.relpath(os.path.join(r, f), wt)
            if rel not in have and in_scope(rel): os.remove(os.path.join(r, f)); d += 1
    log(f"export: {len(files)} files in scope, {n} updated, {d} removed")

def imp(wt, desk, index=None):
    files = deskfiles.resolve("state", wt); now = {s for s, _ in files}; n = d = 0
    for s, _ in files: n += safe_copy(os.path.join(wt, s), os.path.join(desk, s))
    if index:
        try: prev = set(json.load(open(index)))
        except (OSError, ValueError): prev = set()
        for rel in sorted(prev - now):
            p = os.path.join(desk, rel)
            if in_scope(rel) and os.path.isfile(p): os.remove(p); d += 1
        tmp = index + ".tmp"; json.dump(sorted(now), open(tmp, "w")); os.replace(tmp, index)
    log(f"import: {len(files)} files, {n} updated, {d} removed")

def git(wt, *a, check=True, capture=False):
    return subprocess.run(["git", "-C", wt, *a], check=check, text=True, capture_output=capture)

def commit(wt, msg, push=False, retries=5):
    if not git(wt, "config", "user.email", check=False, capture=True).stdout.strip():   # fresh clone without identity
        git(wt, "config", "user.name", "desk-bot"); git(wt, "config", "user.email", "desk-bot@users.noreply.github.com")
    changed = [l[3:] for l in git(wt, "status", "--porcelain", capture=True).stdout.splitlines()]
    if not changed: log("commit: nothing changed"); return 0
    # secret gate: scan everything that changed; offending files are dropped from this commit (and removed from the worktree)
    paths = [os.path.join(wt, p.strip('"')) for p in changed if os.path.isfile(os.path.join(wt, p.strip('"')))]
    bad = set()
    if paths:
        lst = os.path.join(wt, ".git", "scan.lst"); open(lst, "w").write("\n".join(paths))
        r = subprocess.run([sys.executable, os.path.join(ROOT, "deploy", "secret_scan.py"), "--quiet", "--files-from", lst], text=True, capture_output=True)
        for line in r.stdout.splitlines():
            bad.add(line.split(":", 1)[0]); log(f"SECRET GATE: {os.path.relpath(line.split(':', 1)[0], wt)} -> {line.rsplit(': ', 1)[-1]} (excluded)")
    for b in bad:
        rel = os.path.relpath(b, wt)
        if git(wt, "cat-file", "-e", f"HEAD:{rel}", check=False).returncode == 0: git(wt, "checkout", "HEAD", "--", rel)
        else: os.remove(b)
    git(wt, "add", "-A")
    if git(wt, "diff", "--cached", "--quiet", check=False).returncode == 0: log("commit: nothing left after secret gate"); return 0
    git(wt, "commit", "-q", "-m", msg)
    log(f"commit: {len(changed)} path(s) changed, {len(bad)} excluded by secret gate")
    if not push: return 0
    for i in range(retries):
        if git(wt, "push", "-q", "origin", "HEAD:state", check=False).returncode == 0: log("push ok"); return 0
        log(f"push rejected (try {i + 1}/{retries}) -> fetch + rebase -X theirs")
        git(wt, "fetch", "-q", "origin", "state", check=False)
        if git(wt, "rebase", "-q", "-X", "theirs", "origin/state", check=False).returncode != 0:
            git(wt, "rebase", "--abort", check=False); git(wt, "reset", "-q", "--soft", "origin/state"); git(wt, "commit", "-q", "-m", msg + " (re-applied)", check=False)
        time.sleep(2 + 3 * i)
    log("push FAILED after retries (state kept locally, next commit retries)"); return 1

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("cmd", choices=["export", "import", "commit"]); ap.add_argument("a"); ap.add_argument("b", nargs="?")
    ap.add_argument("-m", default="state"); ap.add_argument("--push", action="store_true"); ap.add_argument("--retries", type=int, default=5); ap.add_argument("--index")
    x = ap.parse_args()
    if x.cmd == "export": export(x.a, x.b)
    elif x.cmd == "import": imp(x.a, x.b, x.index)
    else: sys.exit(commit(x.a, x.m, x.push, x.retries))
