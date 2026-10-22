#!/usr/bin/env bash
# meme sleeve wrapper: run_meme.sh pipeline|risk   (SIMULATED fills only; no wallet, no keys needed)
# cron wraps the callers in flock -n (no overlapping runs). 2026-10-20 19:5x: risk = fast-exit loop (5 checks/min, < 60 s);
# pipeline and risk no longer block each other (meme_positions.json writes use the short .pos.lock).
set -uo pipefail
cd "$HOME/.desk"; mkdir -p logs
t0=$EPOCHREALTIME
"$HOME/.desk/venv/bin/python" meme.py "$1" >> logs/meme_run.log 2>&1; rc=$?
dur=$(awk -v a="$t0" -v b="$EPOCHREALTIME" 'BEGIN{printf "%.1f", b-a}')
echo "$(date '+%Y-%m-%d %H:%M:%S %Z') run_meme $1 done rc=$rc ${dur}s" >> logs/meme_run.log
[ $rc -ne 0 ] && echo "$(date '+%Y-%m-%d %H:%M:%S %Z') [RISK] meme.py $1 exit=$rc (see logs/meme_run.log)" >> logs/meme.log
# dashboard: share the cron build lock (wait up to 20s, never run two builds at once)
# (risk: skipped - the 1-min cron build covers it and the fast-exit loop must stay < 60 s)
[ "$1" = "pipeline" ] && { flock -w 20 "$HOME/.desk/.build.lock" "$HOME/.desk/venv/bin/python" build_dashboard.py >> logs/dashboard.log 2>&1 || true; }
exit $rc
