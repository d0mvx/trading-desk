#!/usr/bin/env bash
# Box -> GitHub Actions cutover into d0mvx/trading-desk (subfolder desk2/, workflow desk2.yml, branch state-desk2,
# secrets DESK2_*). The old desk-live workflow and its `state` branch are never touched. Never prints values.
set -euo pipefail
cd /workspace/desk2; R=d0mvx/trading-desk; PY=.venv/bin/python
for n in TYPESAFE_API_KEY HELIUS_API_KEY NGROK_AUTHTOKEN; do printf '%s' "${!n}" | gh secret set DESK2_$n -R $R; done
gh secret set DESK2_VAPID_PRIVATE_KEY -R $R < .secrets/vapid_private.pem
gh secret set DESK2_VAPID_PUBLIC_KEY  -R $R < .secrets/vapid_public.txt
gh secret set DESK2_APP_TOKEN         -R $R < .secrets/app_token
gh secret set DESK2_DATA_PATH         -R $R < .secrets/data_path
gh secret set DESK2_STATE_KEY         -R $R < .secrets/state_key
export DESK_STATE_KEY="$(cat .secrets/state_key)"
git remote get-url origin >/dev/null 2>&1 || git remote add origin https://github.com/$R.git   # used ONLY for state-desk2 / handoff-desk2
$PY -c "import sys; sys.path.insert(0,'gh'); import runner as R; R.save_state('box', note='initial (box, pre-cutover)')"
gh workflow run desk2.yml -R $R --ref main -f slot=a -f pred=box
$PY gh/box_handoff.py
