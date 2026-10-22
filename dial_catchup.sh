#!/usr/bin/env bash
# dial_catchup.sh — hourly self-heal for the QUANT dial (cron #DESK). Runs run_dial.sh only if
#   (a) the newest dial file is missing or its generated_at is > 20 h old (missed 06:00 NY run, box paused/down), or
#   (b) today's (Berlin) dial file is missing although the 06:00 NY run is already past (>= 06:30 NY), or
#   (c) the newest dial has fetch errors (inputs DEGRADED because a source failed, not because data is stale).
# Never touches dial rules/thresholds; it only re-runs the normal job. Skips 05:50-06:30 NY (main run window).
set -uo pipefail
cd "$HOME/.desk"
ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
nyhm=$(TZ=America/New_York date +%H%M)
if [ "$nyhm" -ge 0550 ] && [ "$nyhm" -lt 0630 ]; then exit 0; fi
why=$("$HOME/.desk/venv/bin/python" - "$nyhm" <<'PY'
import sys, glob, json, datetime as dt
from zoneinfo import ZoneInfo
B = ZoneInfo("Europe/Berlin"); now = dt.datetime.now(B); nyhm = int(sys.argv[1])
files = sorted(glob.glob("dial/*.json"))
if not files: print("no dial file"); sys.exit()
try:
    d = json.load(open(files[-1])); age = (now - dt.datetime.fromisoformat(d["generated_at"])).total_seconds() / 3600
except Exception as e:
    print(f"unreadable {files[-1]}: {e}"); sys.exit()
today = f"dial/{now.date().isoformat()}.json"
if age > 20: print(f"newest dial {files[-1]} is {age:.1f}h old (>20h)")
elif nyhm >= 630 and not glob.glob(today): print(f"{today} missing after 06:00 NY")
elif d.get("errors"): print(f"fetch errors {sorted(d['errors'])} degraded={d.get('degraded')}")
PY
)
[ -z "$why" ] && exit 0
echo "$(ts) [QUANT] catch-up run: $why" >> logs/quant.log
exec flock -n "$HOME/.desk/.dial.lock" "$HOME/.desk/run_dial.sh"
