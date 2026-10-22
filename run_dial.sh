#!/usr/bin/env bash
# QUANT dial wrapper: writes ~/.desk/dial/YYYY-MM-DD.json, logs a [QUANT] summary.
set -uo pipefail
cd "$HOME/.desk"
set -a; [ -f "$HOME/.desk/alpaca.env" ] && . "$HOME/.desk/alpaca.env"; set +a   # github: no file -> ALPACA_KEY/SECRET from env
export ALPACA_PAPER=1
mkdir -p logs dial
ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
out=$("$HOME/.desk/venv/bin/python" quant_dial.py 2>>logs/quant.err); rc=$?
if [ $rc -eq 0 ]; then
  echo "$out" | "$HOME/.desk/venv/bin/python" -c '
import json,sys; d=json.load(sys.stdin)
src=",".join("%s:%s" % (k,v.split("(")[0]) for k,v in sorted(d.get("sources",{}).items()) if v!="fred")
print("[QUANT] dial meme %s stocks %s crypto %s | degraded=%s | crypto targets=%s%s" % (d["dial"]["meme"],d["dial"]["stocks"],d["dial"]["crypto"],",".join(d["degraded"]) or "none",d["crypto_targets"]["weights"] or "cash"," | fallback src="+src if src else ""))' | sed "s/^/$(ts) /" >> logs/quant.log
else
  echo "$(ts) [QUANT] ERROR exit=$rc (see logs/quant.err)" >> logs/quant.log
fi
"$HOME/.desk/venv/bin/python" build_dashboard.py >/dev/null 2>&1 || true
exit $rc
