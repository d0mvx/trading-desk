# shellcheck shell=bash
# Shared settings for the box sync scripts. Token: env GITHUB_TOKEN only (fine-grained, this repo); never written to disk.
REPO="${DESK_REPO:-d0mvx/trading-desk}"
DESK="${DESK_DIR:-$HOME/.desk}"
SYNC="${DESK_SYNC_DIR:-$HOME/.desk-sync}"          # dedicated clones: $SYNC/main, $SYNC/state (never edited by hand)
URL="https://github.com/$REPO.git"
PY="$DESK/venv/bin/python"; [ -x "$PY" ] || PY=python3
ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
need_token() { [ -n "${GITHUB_TOKEN:-}" ] || { echo "GITHUB_TOKEN not set" >&2; exit 2; }; }
# git with the token passed through a one-shot credential helper (reads the env var; nothing stored in .git/config)
g() { git -c credential.helper= -c credential.helper='!f() { echo username=x-access-token; echo "password=$GITHUB_TOKEN"; }; f' "$@"; }
api() {  # api METHOD PATH [JSON]  -> body on stdout
  curl -sS -X "$1" -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/vnd.github+json" \
       -H "X-GitHub-Api-Version: 2022-11-28" "https://api.github.com/repos/$REPO$2" ${3:+-d "$3"}
}
clone_branch() {  # clone_branch BRANCH DIR  -> fresh, clean checkout of origin/BRANCH in DIR
  local b=$1 d=$2
  if [ ! -d "$d/.git" ]; then mkdir -p "$(dirname "$d")"; g clone -q --branch "$b" --single-branch "$URL" "$d"; fi
  g -C "$d" fetch -q origin "$b" && git -C "$d" checkout -q -B "$b" "origin/$b" && git -C "$d" reset -q --hard "origin/$b" && git -C "$d" clean -qfd
  git -C "$d" config user.name desk-bot; git -C "$d" config user.email desk-bot@users.noreply.github.com
}
DESK_LOCKS=(.gate.lock .risk.lock .meme.lock .pos.lock .riskstate.lock .shadow.lock .newpairs.lock .build.lock .herenow.lock .alp.lock .lists.lock .dial.lock .wallet.lock .rejtrack.lock)
wait_desk_idle() {  # wait until no desk job holds a lock (max ~2 min each)
  for l in "${DESK_LOCKS[@]}"; do [ -e "$DESK/$l" ] && flock -w 130 "$DESK/$l" true; done; sleep 2
}
in_protected_window() {  # same windows as gh/desk_loop.py (no switch-over minutes before scheduled Alpaca orders)
  "$PY" - "$1" <<'PY'
import sys, datetime as dt; sys.path.insert(0, sys.argv[1] + "/gh"); import desk_loop as L
from zoneinfo import ZoneInfo
now = dt.datetime.now(ZoneInfo("Europe/Berlin")); sys.exit(0 if L.protected_end(now + dt.timedelta(minutes=10)) != now + dt.timedelta(minutes=10) else 1)
PY
}
