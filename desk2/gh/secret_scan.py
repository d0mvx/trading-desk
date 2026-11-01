"""Pre-push secret scan: every tracked/staged file must not contain any secret value (prints names only)."""
import os, subprocess, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = {k: os.environ.get(k) for k in ("TYPESAFE_API_KEY", "HELIUS_API_KEY", "NGROK_AUTHTOKEN", "GITHUB_TOKEN", "GH_TOKEN", "DESK_APP_PASSWORD")}
for n in ("app_token", "data_path", "vapid_public.txt", "state_key"):
    p = os.path.join(ROOT, ".secrets", n)
    if os.path.exists(p): S[n] = open(p).read().strip()
pem = os.path.join(ROOT, ".secrets/vapid_private.pem")
if os.path.exists(pem):
    S["vapid_private"] = "".join(l for l in open(pem).read().splitlines() if "-----" not in l)
S = {k: v for k, v in S.items() if v and len(v) >= 8 and k != "vapid_public.txt"}
files = subprocess.run(["git", "ls-files", "-c", "-o", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout.split()
bad = []
for f in files:
    blob = subprocess.run(["git", "show", f":{f}"], cwd=ROOT, capture_output=True).stdout if subprocess.run(
        ["git", "cat-file", "-e", f":{f}"], cwd=ROOT, capture_output=True).returncode == 0 else open(os.path.join(ROOT, f), "rb").read()
    t = blob.decode(errors="ignore")
    bad += [(f, k) for k, v in S.items() if v in t]
    for forbidden in (".secrets/", "desk.db", "logs/", ".venv/"):
        if f.startswith(forbidden) or f == forbidden.rstrip("/"): bad.append((f, "forbidden path"))
print(f"secret scan: {len(files)} files, {len(S)} secret values checked, {len(bad)} hits")
for b in bad: print("  HIT", *b)
sys.exit(1 if bad else 0)
