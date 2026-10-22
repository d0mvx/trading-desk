#!/usr/bin/env python3
"""Resolve the code / state allowlists (deploy/code_manifest.txt, deploy/state_manifest.txt) against a desk dir.
Usage: deskfiles.py code|state DESK_DIR   -> prints "src<TAB>dst" per file (relative paths), sorted.
Hard deny-list below always wins, whatever the manifest says (defence in depth for the PUBLIC repo)."""
import os, sys, glob, fnmatch
HERE = os.path.dirname(os.path.abspath(__file__))
DENY = ["*.env", "**/*.env", "*.env.*", "alpaca.env", "sec.env", "jev.env", "dash_token", "herenow_site.json", "**/herenow_site.json",
        "public_url.txt", "*.pem", "*.key", "**/id_*", "*keypair*.json", "*wallet*.key", "**/credentials", ".herenow*/**", ".herenow*",
        "dashboard/**", "logs/herenow.log", "venv/**", "bin/**", "backup_*/**", "archive/**", "research/**", "tests/backtest/**",
        "**/__pycache__/**", "*.pyc", "**/*.pyc", ".*.lock", "**/.*.lock", "*.tmp", "**/*.tmp", "**/.*.tmp", ".gt_calls"]
ALLOW_DOTENV = {"jev.env.example", "sec.env.example", "dashboard/apple-touch-icon.png"}   # static icon herenow_publish needs

def denied(rel):
    if rel in ALLOW_DOTENV: return False
    return any(fnmatch.fnmatch(rel, p) for p in DENY)

def resolve(kind, desk):
    rules = [l.strip() for l in open(f"{HERE}/{kind}_manifest.txt") if l.strip() and not l.lstrip().startswith("#")]
    inc = [r for r in rules if not r.startswith("!")]; exc = [r[1:] for r in rules if r.startswith("!")]
    out = {}
    for r in inc:
        src, _, dst = (x.strip() for x in r.partition("->"))
        for p in glob.glob(src, root_dir=desk, recursive=True, include_hidden=True):
            if not os.path.isfile(os.path.join(desk, p)) or os.path.islink(os.path.join(desk, p)): continue
            if any(fnmatch.fnmatch(p, e) for e in exc) or denied(p): continue
            out[p] = dst if dst and "*" not in src else p
    return sorted(out.items())

if __name__ == "__main__":
    for s, d in resolve(sys.argv[1], sys.argv[2]): print(f"{s}\t{d}")
