#!/usr/bin/env bash
# push_code.sh [-m "message"] [--dry-run]
# Box -> GitHub main: CODE ONLY (deploy/code_manifest.txt), e.g. after Backtest approved a change in ~/.desk.
# Gates: secret scan (patterns + the box's real secret values) must be clean, pytest (66 risk tests) must pass.
# Never force-pushes. The running GitHub job picks the new code up at its next handover (<= 6 h) .
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
MSG="code: sync from box $(date '+%Y-%m-%d %H:%M %Z')"; DRY=0
while [ $# -gt 0 ]; do case "$1" in -m) MSG="$2"; shift 2 ;; --dry-run) DRY=1; shift ;; *) echo "usage: $0 [-m msg] [--dry-run]"; exit 2 ;; esac; done
need_token
exec 9>"$SYNC.push.lock"; flock -n 9 || { echo "another push_code is running"; exit 1; }
clone_branch main "$SYNC/main"
R="$SYNC/main"
"$PY" "$R/deploy/export_code.py" "$DESK" "$R"
git -C "$R" add -A -n >/dev/null
CHANGED=$(git -C "$R" status --porcelain | awk '{print $2}')
[ -z "$CHANGED" ] && { echo "$(ts) push_code: nothing to push"; exit 0; }
echo "$(ts) push_code: changed files:"; echo "$CHANGED" | sed 's/^/  /'
# secret gate on the WHOLE tree (not only the diff); *.md docs are redacted first
( cd "$R" && "$PY" deploy/secret_scan.py --redact-md --local-secrets "$DESK" $(git ls-files -co --exclude-standard) ) \
  || { echo "$(ts) push_code: SECRET SCAN FAILED -> nothing pushed (findings above, values never printed)"; exit 3; }
( cd "$DESK" && "$PY" -m pytest tests --ignore=tests/backtest -q -p no:cacheprovider ) \
  || { echo "$(ts) push_code: TESTS FAILED -> nothing pushed"; exit 4; }
git -C "$R" add -A
git -C "$R" commit -q -m "$MSG"
if [ "$DRY" = 1 ]; then echo "$(ts) push_code: dry-run, commit prepared in $R, not pushed"; git -C "$R" show --stat HEAD | tail -n +5; exit 0; fi
for i in 1 2 3; do
  g -C "$R" push -q origin HEAD:main && { echo "$(ts) push_code: pushed $(git -C "$R" rev-parse --short HEAD)"; exit 0; }
  g -C "$R" fetch -q origin main && git -C "$R" rebase -q origin/main || { git -C "$R" rebase --abort; echo "conflict with remote main -> resolve by hand"; exit 5; }
done
exit 6
