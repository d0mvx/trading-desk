#!/usr/bin/env bash
# Alpaca PAPER sleeve wrapper: run_alp.sh stocks|crypto|kill|lists [--dry-run]
# paper only (alp_common hard-wires paper=True and refuses ALPACA_PAPER!=1); keys from alpaca.env, never printed.
set -uo pipefail
cd "$HOME/.desk"; mkdir -p logs
export ALPACA_PAPER=1 PYTHONUNBUFFERED=1
[ -f "$HOME/.desk/sec.env" ] && { set -a; . "$HOME/.desk/sec.env"; set +a; }
case "$1" in
  stocks) s=stocks.py ;; crypto) s=crypto.py ;; kill) s=killswitch.py ;;
  lists)  shift; flock -n "$HOME/.desk/.lists.lock" bash -c '"$HOME/.desk/venv/bin/python" lists_insiders.py; r=$?; "$HOME/.desk/venv/bin/python" lists_drift.py || r=$?; exit $r' >> logs/lists.log 2>&1; rc=$?
          echo "$(date '+%Y-%m-%d %H:%M:%S %Z') [LISTS] done rc=$rc" >> logs/lists.log; exit $rc ;;
  *) echo "usage: run_alp.sh stocks|crypto|kill|lists [--dry-run]"; exit 2 ;;
esac
shift
flock -w 120 "$HOME/.desk/.alp.lock" "$HOME/.desk/venv/bin/python" "$s" "$@" >> logs/alpaca_run.log 2>&1; rc=$?
echo "$(date '+%Y-%m-%d %H:%M:%S %Z') run_alp $s $* rc=$rc" >> logs/alpaca_run.log
exit $rc
