#!/usr/bin/env bash
# rollback.sh  --  make the box the live desk again. DO NOT RUN without Dominic's go.
#  1. remove GH_LIVE from branch `state` (queued/next runs then do nothing)
#  2. cancel every queued / in-progress desk-live run, wait until they finished (their always() step saves state)
#  3. pull the final state into ~/.desk, 4. restore the "#GHCUT# " cron lines, remove ~/.desk/.github_live
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
TOOLS="$(dirname "$(dirname "$(readlink -f "$0")")")"
need_token
clone_branch state "$SYNC/state"
if [ -f "$SYNC/state/GH_LIVE" ]; then
  git -C "$SYNC/state" rm -q GH_LIVE && git -C "$SYNC/state" commit -q -m "state: rollback to box (GH_LIVE removed)"
  for i in 1 2 3 4 5; do g -C "$SYNC/state" push -q origin HEAD:state && break; g -C "$SYNC/state" fetch -q origin state; git -C "$SYNC/state" rebase -q -X theirs origin/state; sleep 3; done
fi
for st in queued in_progress waiting pending; do
  for id in $(api GET "/actions/workflows/desk.yml/runs?status=$st&per_page=50" | jq -r '.workflow_runs[].id'); do
    api POST "/actions/runs/$id/cancel" >/dev/null; echo "$(ts) rollback: cancel requested for run $id ($st)"; done
done
for i in $(seq 1 60); do   # up to 10 min for the final state save
  n=0; for st in queued in_progress; do n=$(( n + $(api GET "/actions/workflows/desk.yml/runs?status=$st&per_page=50" | jq '.total_count') )); done
  [ "$n" = 0 ] && break; sleep 10
done
touch "$DESK/.github_live"   # allow the final pull into ~/.desk
B="$DESK/backup_$(date +%Y%m%d_%H%M)_rollback"; mkdir -p "$B"; crontab -l > "$B/crontab_before.txt"
"$(dirname "$(readlink -f "$0")")/pull_state.sh" || { rm -f "$DESK/.github_live"; echo "final pull FAILED -> cron NOT restored, check by hand"; exit 5; }
rm -f "$DESK/.github_live"
sed 's/^#GHCUT# //' "$B/crontab_before.txt" > "$B/crontab_after.txt"; crontab "$B/crontab_after.txt"
echo "$(ts) rollback: $(diff "$B/crontab_before.txt" "$B/crontab_after.txt" | grep -c '^>') box cron line(s) restored; box is live again"
