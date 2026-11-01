#!/usr/bin/env bash
# runner copy of bin/desk_supervisor.sh (relative paths): restart on exit, kill+restart after 2 failed health checks.
cd "$(dirname "$0")/.."
export DESK_DB="$PWD/desk.db" DESK_PORT=8787 PYTHONUNBUFFERED=1
PY="${PY:-.venv/bin/python}"; mkdir -p logs
trap 'kill $PID 2>/dev/null; exit 0' TERM INT
while true; do
  echo "$(date -Is) starting desk" >> logs/supervisor.log
  $PY -m desk.main >> logs/desk_stdout.log 2>&1 &
  PID=$!
  for i in $(seq 1 30); do kill -0 $PID 2>/dev/null || break; sleep 5; done; strikes=0
  while kill -0 $PID 2>/dev/null; do
    if $PY -m desk.health >> logs/health.log 2>&1; then strikes=0; else strikes=$((strikes+1)); fi
    if [ $strikes -ge 2 ]; then echo "$(date -Is) unhealthy twice, restarting" >> logs/supervisor.log; kill $PID; sleep 5; kill -9 $PID 2>/dev/null; break; fi
    sleep 60 & wait $!
  done
  wait $PID 2>/dev/null
  echo "$(date -Is) desk exited, restart in 5s" >> logs/supervisor.log
  sleep 5
done
