#!/usr/bin/env bash
# cutover.sh  --  make GitHub the live desk. DO NOT RUN without Dominic's go. Order matters:
#  1. pre-checks (token, workflow on main, required secrets present, not within 10 min of a scheduled Alpaca order)
#  2. comment out the box's #DESK trading/publish cron lines (prefix "#GHCUT# "); watchdog.sh + #WALLET_OOS stay
#  3. wait until no desk job holds a lock, then seed branch `state` with the box's CURRENT state + GH_LIVE flag
#  4. dispatch the workflow; mark ~/.desk/.github_live (enables pull_state.sh)
# Undo: rollback.sh
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
TOOLS="$(dirname "$(dirname "$(readlink -f "$0")")")"
need_token
REQ=(ALPACA_KEY ALPACA_SECRET SEC_USER_AGENT HERENOW_API_KEY HERENOW_SITE_SLUG HERENOW_SITE_PASSWORD HERENOW_WIDGET_SLUG HERENOW_WIDGET_PATH)
have=$(api GET "/actions/secrets?per_page=100" | jq -r '.secrets[].name')
for s in "${REQ[@]}"; do grep -qx "$s" <<<"$have" || { echo "missing GitHub secret $s -> abort (nothing changed)"; exit 3; }; done
api GET "/contents/.github/workflows/desk.yml?ref=main" | jq -e .sha >/dev/null || { echo "workflow not on main -> abort"; exit 3; }
if in_protected_window "$TOOLS"; then echo "within 10 min of a scheduled Alpaca order window -> try later"; exit 4; fi
B="$DESK/backup_$(date +%Y%m%d_%H%M)_cutover"; mkdir -p "$B"; crontab -l > "$B/crontab.txt"
echo "$(ts) cutover: crontab backed up to $B/crontab.txt"
crontab -l | awk '/#DESK[[:space:]]*$/ && $0 !~ /^[[:space:]]*#/ && $0 !~ /watchdog\.sh/ {print "#GHCUT# " $0; next} {print}' > "$B/crontab_after.txt"
crontab "$B/crontab_after.txt"
echo "$(ts) cutover: $(grep -c '^#GHCUT# ' "$B/crontab_after.txt") box cron line(s) disabled"
wait_desk_idle
clone_branch state "$SYNC/state"
"$PY" "$TOOLS/gh/state_sync.py" export "$DESK" "$SYNC/state"
echo "live since $(date -Iseconds) (box cutover)" > "$SYNC/state/GH_LIVE"
"$PY" "$TOOLS/gh/state_sync.py" commit "$SYNC/state" -m "state: cutover seed from box $(date '+%Y-%m-%d %H:%M %Z') + GH_LIVE" --push \
  || { echo "state push FAILED -> restoring box cron"; crontab "$B/crontab.txt"; exit 5; }
api POST "/actions/workflows/desk.yml/dispatches" '{"ref":"main"}' >/dev/null
date -Iseconds > "$DESK/.github_live"
echo "$(ts) cutover: done. GitHub run dispatched; watch https://github.com/$REPO/actions . Box state now comes from pull_state.sh."
