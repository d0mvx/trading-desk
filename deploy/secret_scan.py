#!/usr/bin/env python3
"""Secret scan for the PUBLIC repo. Prints  path:line: RULE  per finding, NEVER the matched value. Exit 1 on findings.
Usage: secret_scan.py [--local-secrets DESK_DIR] [--files-from LIST] PATH...
  Pattern rules: private keys, GitHub/Alpaca/AWS/Slack tokens, bearer/password assignments, e-mail addresses,
  the private widget feed name (by sha256), Solana secret-key material.
  Literal rules: the exact secret VALUES (>= 6 chars) taken from env vars (GitHub Actions secrets) and, with
  --local-secrets, from the box files alpaca.env, sec.env, dash_token, herenow_site.json, ~/.herenow/credentials.
  Values are only held in memory for comparison."""
import os, re, sys, json, argparse
ENV_SECRETS = ["ALPACA_KEY", "ALPACA_SECRET", "HERENOW_API_KEY", "HERENOW_SITE_SLUG", "HERENOW_SITE_PASSWORD", "HERENOW_WIDGET_SLUG",
               "HERENOW_WIDGET_PATH", "SEC_USER_AGENT", "DASH_TOKEN", "FRED_API_KEY", "JEV_API_KEY", "TYPESAFE_API_KEY", "GITHUB_TOKEN", "GH_TOKEN"]
EMAIL_OK = re.compile(r"(@example\.(com|org|net)|^your-email@|noreply|@users\.noreply\.github\.com|^git@github\.com)", re.I)
RULES = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github-token", re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b|\bgithub_pat_[A-Za-z0-9_]{40,}\b")),
    ("alpaca-key-id", re.compile(r"\b(PK|AK|CK)[A-Z0-9]{16,24}\b")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("bearer-literal", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")),
    ("secret-assignment", re.compile(r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b[\"']?\s*[:=]\s*[\"']([A-Za-z0-9_\-+/=.]{12,})[\"']")),
    ("env-assignment", re.compile(r"(?m)^\s*(export\s+)?(ALPACA_KEY|ALPACA_SECRET|HERENOW_API_KEY|FRED_API_KEY|JEV_API_KEY|TYPESAFE_API_KEY)\s*=\s*\S{8,}")),
    ("solana-secret-b58", re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{86,90}(?![1-9A-HJ-NP-Za-km-z])")),
    ("keypair-int-array", re.compile(r"\[\s*(\d{1,3}\s*,\s*){63}\d{1,3}\s*\]")),
    ("seed-phrase-hint", re.compile(r"(?i)\b(seed phrase|mnemonic|private[_ ]key)\b\s*[:=]\s*\S")),
]
# private widget feed name: only its sha256 is stored here (the name itself must not appear in the public repo)
FEED_SHA = {"d0a67451d38e1ff52f9672b2da957059ee0f72eb97e279e01188c733b377d927"}
WORDPAIR = re.compile(r"(?i)\b[a-z]{3,12}-[a-z]{3,12}")
def feed_hit(line):
    import hashlib
    return any(hashlib.sha256(m.group(0).lower().encode()).hexdigest() in FEED_SHA for m in WORDPAIR.finditer(line))
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

def literals(local_desk=None):
    vals = {}
    def add(name, v):
        v = (v or "").strip().strip('"\'')
        if len(v) >= 6: vals[v] = name
    for k in ENV_SECRETS: add(f"env:{k}", os.environ.get(k))
    for m in EMAIL.finditer(os.environ.get("SEC_USER_AGENT", "")): add("env:SEC_USER_AGENT-email", m.group(0))
    if local_desk:
        for fn in ("alpaca.env", "sec.env", "jev.env"):
            try:
                for l in open(os.path.join(local_desk, fn)):
                    if "=" in l and not l.lstrip().startswith("#"):
                        k, v = l.split("=", 1); add(f"{fn}:{k.strip()}", v)
                        for m in EMAIL.finditer(v): add(f"{fn}:email", m.group(0))
            except OSError: pass
        try: add("dash_token", open(os.path.join(local_desk, "dash_token")).read())
        except OSError: pass
        try:
            hs = json.load(open(os.path.join(local_desk, "herenow_site.json")))
            for k in ("slug", "password", "widget_path", "widget_slug", "widget_url", "widget_site_url", "siteUrl"): add(f"herenow_site.json:{k}", str(hs.get(k) or ""))
        except (OSError, ValueError): pass
        try:
            for l in open(os.path.expanduser("~/.herenow/credentials")):
                if "=" in l: add("herenow-credentials", l.split("=", 1)[1])
        except OSError: pass
    return vals

B58_ADDR = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")   # Solana mint / wallet address (public), e.g. "token": "<mint>"
ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]+$")                # env var NAME, e.g. "password": "HERENOW_SITE_PASSWORD"
def _assign_ok(m):
    v = m.group(2)
    return bool(B58_ADDR.match(v) or ENV_NAME.match(v))

def load_allow(path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "scan_allowlist.txt")):
    """path-glob<TAB>rule<TAB>reason. Pattern rules only - literal secret values can never be allow-listed."""
    out = []
    try:
        for l in open(path):
            if l.strip() and not l.startswith("#"):
                p = l.rstrip("\n").split("\t"); out.append((p[0], p[1]))
    except OSError: pass
    return out
ALLOW = load_allow()

def allowed(path, rule):
    import fnmatch
    return not rule.startswith("literal(") and any(fnmatch.fnmatch(path, "*" + g) and r == rule for g, r in ALLOW)

def scan_text(path, text, lits):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        if len(line) > 200_000: line = line[:200_000]
        for name, rx in RULES:
            if name == "secret-assignment":
                if any(not _assign_ok(m) for m in rx.finditer(line)): out.append((path, i, name))
            elif rx.search(line): out.append((path, i, name))
        if feed_hit(line): out.append((path, i, "widget-feed-name"))
        for m in EMAIL.finditer(line):
            if not EMAIL_OK.search(m.group(0)): out.append((path, i, "email-address")); break
        for v, name in lits.items():
            if v in line: out.append((path, i, f"literal({name})"))
    return out

def redact_md(path, lits):
    """Docs only (*.md): replace literal secret values / widget feed name / e-mails with [redacted]. Returns count."""
    t = open(path, encoding="utf-8", errors="replace").read(); n0 = t
    for v in sorted(lits, key=len, reverse=True): t = t.replace(v, "[redacted]")
    import hashlib
    t = re.sub(r"(?i)\b([a-z]{3,12}-[a-z]{3,12})[\w.-]*", lambda m: "[redacted]" if hashlib.sha256(m.group(1).lower().encode()).hexdigest() in FEED_SHA else m.group(0), t)
    t = EMAIL.sub(lambda m: m.group(0) if EMAIL_OK.search(m.group(0)) else "[redacted]", t)
    if t != n0: open(path, "w", encoding="utf-8").write(t)
    return int(t != n0)

def iter_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for r, ds, fs in os.walk(p):
                ds[:] = [d for d in ds if d != ".git"]
                for f in fs: yield os.path.join(r, f)
        elif os.path.isfile(p): yield p

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("paths", nargs="*"); ap.add_argument("--local-secrets"); ap.add_argument("--files-from")
    ap.add_argument("--quiet", action="store_true"); ap.add_argument("--redact-md", action="store_true", help="rewrite *.md files in place first")
    a = ap.parse_args(); lits = literals(a.local_secrets)
    paths = list(a.paths) + ([l.rstrip("\n") for l in open(a.files_from) if l.strip()] if a.files_from else [])
    found, n = [], 0
    if a.redact_md:
        r = sum(redact_md(f, lits) for f in iter_files(paths) if f.endswith(".md"))
        print(f"secret_scan: redacted {r} markdown file(s)", file=sys.stderr)
    for f in iter_files(paths):
        try: b = open(f, "rb").read()
        except OSError: continue
        n += 1
        if b"\0" in b[:8192]:   # binary: literal + key-header checks only
            t = b.decode("latin-1"); found += [(f, 0, f"literal({nm})") for v, nm in lits.items() if v in t]
            if b"PRIVATE KEY-----" in b: found.append((f, 0, "private-key"))
            continue
        found += scan_text(f, b.decode("utf-8", "replace"), lits)
    found = [f for f in found if not allowed(f[0], f[2])]
    for p, i, r in found: print(f"{p}:{i}: {r}")
    if not a.quiet: print(f"secret_scan: {n} files, {len(found)} finding(s), {len(lits)} literal secret value(s) checked", file=sys.stderr)
    sys.exit(1 if found else 0)

if __name__ == "__main__": main()
