#!/usr/bin/env bash
# set_secrets.sh  --  copy the box's secret VALUES into GitHub Actions secrets (gh CLI encrypts them). Values are piped
# from the local files straight into `gh secret set`, never echoed. DO NOT RUN without Dominic's go.
set -euo pipefail
. "$(dirname "$(readlink -f "$0")")/common.sh"
need_token; export GH_TOKEN="$GITHUB_TOKEN"
kv() { grep -E "^(export )?$2=" "$1" | tail -1 | cut -d= -f2- | sed -e 's/^["'\'']//' -e 's/["'\'']$//' | tr -d '\n'; }
js() { "$PY" -c "import json,sys; sys.stdout.write(str(json.load(open('$DESK/herenow_site.json'))['$1']))"; }
put() { gh secret set "$1" --repo "$REPO" >/dev/null && echo "set $1"; }
kv "$DESK/alpaca.env" ALPACA_KEY        | put ALPACA_KEY
kv "$DESK/alpaca.env" ALPACA_SECRET     | put ALPACA_SECRET
kv "$DESK/sec.env"    SEC_USER_AGENT    | put SEC_USER_AGENT
kv "$HOME/.herenow/credentials" HERENOW_API_KEY | put HERENOW_API_KEY
js slug        | put HERENOW_SITE_SLUG
js password    | put HERENOW_SITE_PASSWORD
js widget_slug | put HERENOW_WIDGET_SLUG
js widget_path | put HERENOW_WIDGET_PATH
tr -d '\n' < "$DESK/dash_token" | put DASH_TOKEN
