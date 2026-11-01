#!/usr/bin/env bash
# fixed ngrok domain -> 127.0.0.1:8787; retries fast while the predecessor still holds the endpoint.
cd "$(dirname "$0")/.."; mkdir -p logs
NGROK="${NGROK:-ngrok}"
trap 'kill $NP 2>/dev/null; exit 0' TERM INT
while true; do
  echo "$(date -Is) starting ngrok" >> logs/supervisor.log
  $NGROK http 8787 --url=https://relight-stalling-periscope.ngrok-free.dev --log=stdout --log-level=warn >> logs/ngrok.log 2>&1 &
  NP=$!; wait $NP
  echo "$(date -Is) ngrok exited ($?), restart in 2s" >> logs/supervisor.log
  sleep 2
done
