#!/usr/bin/env bash
# dryrun_local.sh [ITERATIONS]  --  run the GitHub loop locally on the box against a COPY of code + state, env-only secrets.
# Paper/simulated only: here.now publish and the live kill switch are excluded; Alpaca sleeves run with --dry-run (no orders);
# the GeckoTerminal rate window is SHARED with the live box (.gt_calls symlink) so both together stay under 10 calls/min.
# State commits go to a throwaway clone of branch `state` (never pushed).
set -euo pipefail
REPO="$(dirname "$(dirname "$(readlink -f "$0")")")"; N="${1:-3}"
DRY=/workspace/dryrun; LIVE="$HOME/.desk"
rm -rf "$DRY"; mkdir -p "$DRY/home/.desk"
git -C "$REPO" archive main | tar -x -C "$DRY/home/.desk"
git clone -q --branch state "$REPO" "$DRY/state"; git -C "$DRY/state" config user.name dryrun; git -C "$DRY/state" config user.email dryrun@example.com
python3 "$REPO/gh/state_sync.py" import "$DRY/state" "$DRY/home/.desk"
ln -s "$LIVE/venv" "$DRY/home/.desk/venv"; ln -s "$LIVE/.gt_calls" "$DRY/home/.desk/.gt_calls"
mkdir -p "$DRY/home/.desk/logs"
for f in alpaca.env sec.env dash_token herenow_site.json; do test ! -e "$DRY/home/.desk/$f"; done; echo "no secret files in dry desk: ok"
(
  # env-var config, exactly like GitHub secrets (values read from the box files, never printed)
  set -a; . "$LIVE/alpaca.env"; . "$LIVE/sec.env"; set +a
  export HOME="$DRY/home" TZ=Europe/Berlin ALPACA_PAPER=1 PYTHONUNBUFFERED=1 HERENOW_REQUIRE_SLUG=1
  export DESK_DASH_OUT="$DRY/home/.desk/dashboard"   # keeps the box's /workspace/desk-dashboard.html Drive mirror untouched
  D="$HOME/.desk"; P="$D/venv/bin/python"
  echo "== pytest"; (cd "$D" && "$P" -m pytest tests --ignore=tests/backtest -q -p no:cacheprovider 2>&1 | tail -1)
  echo "== loop ($N iterations)"
  "$P" "$D/gh/desk_loop.py" --iterations "$N" --exclude herenow_publish --exclude 'run_alp\.sh kill' \
      --state-worktree "$DRY/state" --commit-every 1 --commit-offset 0 --grace 90
  echo "== scheduled jobs forced once (dry-run flags)"
  "$D/run_alp.sh" kill --dry-run; echo "kill --dry-run rc=$?"
  "$D/run_alp.sh" crypto --dry-run; echo "crypto --dry-run rc=$?"
  "$D/run_alp.sh" stocks --dry-run; echo "stocks --dry-run rc=$?"
  "$D/run_strategy.sh" --dry-run >/dev/null; echo "trend --dry-run rc=$?"
  "$D/run_dial.sh"; echo "dial rc=$?"
  "$D/dial_catchup.sh"; echo "dial_catchup rc=$?"
)
