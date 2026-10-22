#!/usr/bin/env python3
"""Mirror the CODE allowlist from a desk dir into a repo checkout (branch main).
Usage: export_code.py SRC_DESK DST_REPO   -> prints added/changed/removed. Repo-only files (README.md, .github/, gh/,
deploy/, box/, requirements*.txt, pytest.ini, .gitignore) are never touched. *.md docs are redacted later by secret_scan."""
import os, sys, shutil, fnmatch, filecmp
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import deskfiles
src, dst = sys.argv[1], sys.argv[2]
files = deskfiles.resolve("code", src); want = {d for _, d in files}
rules = [l.strip().partition("->") for l in open(os.path.join(deskfiles.HERE, "code_manifest.txt")) if l.strip() and not l.startswith("#")]
scope = [(d.strip() if d.strip() else s.strip()) for s, _, d in rules]
REPO_ONLY = ("README.md", ".gitignore", "pytest.ini", "requirements.txt", "requirements-dev.txt")
REPO_DIRS = (".git/", ".github/", "gh/", "deploy/", "box/")
ch = {"added": 0, "changed": 0, "removed": 0}
for s, d in files:
    sp, dp = os.path.join(src, s), os.path.join(dst, d)
    if os.path.exists(dp) and filecmp.cmp(sp, dp, shallow=False): continue
    ch["changed" if os.path.exists(dp) else "added"] += 1
    os.makedirs(os.path.dirname(dp) or ".", exist_ok=True); shutil.copy2(sp, dp); print("  update", d)
for r, ds, fs in os.walk(dst):
    ds[:] = [x for x in ds if x != ".git"]
    for f in fs:
        rel = os.path.relpath(os.path.join(r, f), dst)
        if rel in REPO_ONLY or rel.startswith(REPO_DIRS) or rel in want: continue
        if any(fnmatch.fnmatch(rel, p) for p in scope):
            os.remove(os.path.join(r, f)); ch["removed"] += 1; print("  remove", rel)
print("export_code:", ch, f"{len(files)} files in allowlist")
