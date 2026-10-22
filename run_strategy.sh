#!/usr/bin/env bash
# Runner wrapper: paper only. Usage: run_strategy.sh [--dry-run]
set -uo pipefail
cd "$HOME/.desk"
set -a; [ -f "$HOME/.desk/alpaca.env" ] && . "$HOME/.desk/alpaca.env"; set +a   # github: no file -> ALPACA_KEY/SECRET from env
export ALPACA_PAPER=1 PYTHONUNBUFFERED=1
export TREND_SHARE=${TREND_SHARE:-0.35}   # article: TREND 35% of the Alpaca PAPER account (re-enabled 2026-10-20)
mkdir -p logs
"$HOME/.desk/venv/bin/python" strategy.py "$@" 2>&1 | while IFS= read -r l; do printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$l"; done | tee -a logs/runner.log
rc=${PIPESTATUS[0]}
printf '%s [RUNNER] exit=%s args=%s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$rc" "$*" >> logs/runner.log
"$HOME/.desk/venv/bin/python" build_dashboard.py >/dev/null 2>&1 || true
exit $rc
