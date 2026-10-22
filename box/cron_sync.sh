#!/usr/bin/env bash
# cron_sync.sh pull|push  --  cron entry point for the box sync (tags #GHSYNC in crontab).
# cron has no GITHUB_TOKEN in its env, so it is read from ~/.config/desk-sync/github_token (chmod 600, outside every repo;
# fine-grained, this repo only). The tools checkout ($HOME/.desk-sync/tools) is fast-forwarded first.
set -uo pipefail
TF="$HOME/.config/desk-sync/github_token"
[ -n "${GITHUB_TOKEN:-}" ] || { [ -r "$TF" ] && GITHUB_TOKEN=$(tr -d '\n' < "$TF"); }
export GITHUB_TOKEN
T="$HOME/.desk-sync/tools"
. "$T/box/common.sh"; need_token
git -C "$T" pull -q --ff-only origin main 2>/dev/null || echo "$(ts) tools fast-forward failed (kept current tools)"
case "${1:-}" in
  pull) exec "$T/box/pull_state.sh" ;;
  push) exec "$T/box/push_code.sh" ;;
  *) echo "usage: cron_sync.sh pull|push"; exit 2 ;;
esac
