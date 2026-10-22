#!/usr/bin/env bash
# Keeps the token-gated dashboard server + cloudflared quick tunnel alive; records the public URL.
# Quick-tunnel URLs (*.trycloudflare.com) CHANGE whenever cloudflared restarts.
D="$HOME/.desk"; cd "$D"; mkdir -p logs
ts() { date '+%Y-%m-%d %H:%M:%S %Z'; }
if ! curl -s -o /dev/null -m 5 "http://127.0.0.1:8080/$(cat dash_token)/"; then
  pkill -f "$D/serve.py" ; sleep 1
  nohup "$D/venv/bin/python" "$D/serve.py" >> logs/http.err 2>&1 &
  echo "$(ts) [CHIEF] dashboard server (re)started" >> logs/watchdog.log; sleep 1
fi
if [ -f "$D/tunnel_disabled" ]; then
  pkill -f "$D/bin/cloudflared" 2>/dev/null; rm -f "$D/public_url.txt"
elif ! pgrep -f "$D/bin/cloudflared tunnel" >/dev/null; then
  : > logs/cloudflared.log
  nohup "$D/bin/cloudflared" tunnel --no-autoupdate --protocol http2 --url http://127.0.0.1:8080 >> logs/cloudflared.log 2>&1 &
  echo "$(ts) [CHIEF] cloudflared quick tunnel (re)started -> public URL will change" >> logs/watchdog.log
  for i in $(seq 1 30); do grep -qo 'https://[a-z0-9-]*\.trycloudflare\.com' logs/cloudflared.log && break; sleep 1; done
fi
[ -f "$D/tunnel_disabled" ] && exit 0
url=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' logs/cloudflared.log | tail -1)
if [ -n "$url" ]; then
  new="$url/$(cat dash_token)/"
  if [ "$(cat public_url.txt 2>/dev/null)" != "$new" ]; then
    umask 077; echo "$new" > public_url.txt
    echo "$(ts) [CHIEF] public URL updated (${url})" >> logs/watchdog.log
  fi
fi
