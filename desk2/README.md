# desk2 — PAPER memecoin desk (pump.fun graduations)

PAPER only: LIVE is hard-locked, no order path exists. Runs 24/7 on GitHub Actions (`.github/workflows/desk.yml`):
one ~5h50m job per run, chained by self-dispatch with an explicit handoff (`gh/runner.py`), state encrypted on
branch `state` (`gh/state.py`). The app is password-protected and served via ngrok.
