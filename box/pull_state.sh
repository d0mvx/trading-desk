#!/usr/bin/env bash
# pull_state.sh [--into DIR]
# GitHub branch `state` -> ~/.desk, so Backtest/Scan/other bots and the backups see current data.
# Only allowed while GitHub is the live desk (marker ~/.desk/.github_live from cutover.sh); otherwise the box's own cron
# owns the state and a pull would overwrite live data. --into DIR copies into another dir instead (inspection, always allowed).
# Suggested cron AFTER cutover (not installed):  */5 * * * * bash -lc '$HOME/.desk-sync/tools/box/pull_state.sh' >> $HOME/.desk/logs/gh_pull.log 2>&1
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
TOOLS="$(dirname "$(dirname "$(readlink -f "$0")")")"
INTO="$DESK"; [ "${1:-}" = "--into" ] && INTO="$2"
need_token
if [ "$INTO" = "$DESK" ] && [ ! -f "$DESK/.github_live" ]; then
  echo "$(ts) pull_state: refused - box is the live desk (no $DESK/.github_live). Use --into DIR to inspect."; exit 1; fi
exec 9>"$SYNC.pull.lock"; flock -n 9 || exit 0
clone_branch state "$SYNC/state"
mkdir -p "$INTO"
"$PY" "$TOOLS/gh/state_sync.py" import "$SYNC/state" "$INTO" --index "$SYNC/state_index.$(echo "$INTO" | md5sum | cut -c1-8).json"
echo "$(ts) pull_state: $(git -C "$SYNC/state" log -1 --format='%h %s') -> $INTO"
