# Research changelog (autonomous paper-only upgrades)

Every entry: what, why, evidence, backup path, how to revert. Backups contain the touched files + `crontab.txt`.
Revert recipe (generic): `cp -p ~/.desk/<backup>/<file> ~/.desk/<file>` for each listed file, then `./venv/bin/python -m py_compile <file>`.

## 2026-10-20 21:04 — Lead IDs (meme / new pairs / shadow)
- **What:** new `leads.py` (`lead_id(mint) = "L" + mint[:6]`, deterministic, no state). Carried as `"lead"` in: scan candidate +
  reject records (`scan/*.jsonl`), judge decisions, real positions + `meme_trades.jsonl` BUY/SELL records, new-pairs
  `dec_log` records, shadow positions; `[Lxxxxxx]` tag in FILLS BUY/SELL, SHADOW BUY/SELL/CLOSE, RISK per-check lines and the
  "no trade" reason (top-3 kills with the gate that stopped each), so it shows in the dashboard activity log.
- **Why:** trace one coin's whole life: `grep -h L<id> logs/*.log logs/*.jsonl scan/*.jsonl`.
- **Evidence:** compile + `meme.py dry` + `newpairs.py dry` + live runs rc=0; first live buy 21:12 logged `[LF6Kw7c] DACITY / SOL`.
- **Params:** 0. **Backup:** `backup_20261020_2104_leadid_audit/`. **Revert:** restore meme.py, scan.py, newpairs.py, shadow.py; delete leads.py.

## 2026-10-20 21:09 — Risk-rule enforcement audit, meme side (+ tests in `tests/`)
- **What (fixes):**
  1. `meme.book_add()` = the ONLY path that adds a real paper position (main pipeline incl. dip-watchlist buys, and newpairs).
     Under the positions lock it re-checks against the book as it is *now*: daily-DD halt, per-sleeve cap (main 3 / new pairs 2),
     overall cap 4, one position per coin matched on mint **and** pool / pre-graduation pool (no re-buy, no averaging, also
     across sleeves), ticket cap (cost <= ticket% x meme equity). Before: newpairs checked "already held" on mint only and
     neither path re-checked the halt at fill time (a halt firing mid-run could still buy).
  2. Stops vs missing data: a held position with no price was skipped with one log line per minute (silent stop outage).
     Now: `price_missing_since`/`stale_s` on the position, loud `NO PRICE ... [STALE]` line every check after 60 s, and a
     GeckoTerminal fallback (<= 2 calls/min, only while a held coin has no price for >= 20 s) so the stop can still fire.
  3. Daily 4% DD: state was only `risk_state.json`; a deleted file rebased day-open equity to the current (lower) equity and
     lifted an active halt. Now also an append-only journal `logs/risk_state.jsonl`; deleted/corrupt state recovers from it,
     corrupt + no journal fails closed (halted). `daily_halt_active()` used by newpairs.
- **Verified holds (no change needed):** stop-loss fires in the same 12 s check (5 checks/min); risk loop runs every minute;
  halt blocks the main pipeline incl. watchlist entries and the newpairs path; caps already checked under lock for main.
- **Tests:** `tests/run_all.sh` (19 tests, isolated temp dirs, no network, incl. an 18-process concurrent-add test).
- **Params:** 2 (STALE_GT_S=20, STALE_WARN_S=60). **Backup:** `backup_20261020_2109_riskaudit_meme/`.
- **Revert:** restore meme.py + newpairs.py from the backup (tests/ and logs/risk_state.jsonl can stay; they are inert).

## 2026-10-20 21:14 — Control bot + reject tracking + narrative first-seen (research instrumentation, no trading change)
- **What:** (1) `meme.pipeline` adds two shadow baselines per run: `control:top_scan_pass` and `control:random_scan_pass`
  (PumpSwap scan passers, NO judge/RugCheck/dip gates, same fills + exits, virtual only, <= 10 open each by shadow caps).
  (2) `reject_tracker.py` (cron */5, DexScreener only, 0 GT calls): registers every scan reject / scan pass / judge decision
  (<= 15 min old) with the gate that fired, prices it at t0, +1h, +6h, +24h -> `logs/reject_outcomes.jsonl`.
  Note: scan rejects are stored truncated (20 per run), so per-gate counts are a sample. (3) the same job keeps
  `scan/narrative_first_seen.json` (first time each trend term appeared) for the narrative-timing test.
- **Why:** gates must beat a no-gate baseline; per-gate false-negative rates need outcomes of rejected coins.
- **Params:** 0 trading params. **Backup:** `backup_20261020_2114_control_rejects/` (meme.py, shadow.py, crontab).
- **Revert:** restore meme.py; remove the `reject_tracker.py` cron line.

## 2026-10-20 21:16 — Weekly review (Sundays 20:00 Berlin) + dashboard card
- **What:** `weekly_review.py` -> `reviews/weekly_<date>.md` + `reviews/weekly_latest.html`, shown as "WEEKLY REVIEW" card.
  Win rate / avg R by Berlin hour, curve phase, narrative age; shadow + control by category; per-gate shadow cost +
  reject outcomes (+1h/+6h/+24h, FN rate = +6h >= +50%); rule that cost most / 1 to cut (needs n >= 10) / 1 to add (only
  from `reviews/research_candidates.json` entries that passed holdout); gates vs control; turnover; filter-health alarm
  (< 10 rejects/day); monthly routine audit (first Sunday: runs tests/run_all.sh).
- **First run (7d):** real 39 trades, win 36%, avg R +0.04, P&L -$0.20; by phase: PumpSwap 26 trades +$5.59 (avg R +0.45)
  vs bonding curve 13 trades -$5.79 (avg R -0.79) — consistent with upgrade 4 (no main-sleeve curve buys).
- **Backup:** `backup_20261020_2116_weekly_review/` (build_dashboard.py, crontab). **Revert:** restore build_dashboard.py, drop the cron line.

## 2026-10-20 21:24 — STOP ALL switch, meme side (`~/.desk/STOP_ALL` file)
- **What:** `meme.book_add()` (the only path into the real paper book: main pipeline incl. watchlist buys + new pairs) returns
  "STOP_ALL file present" while `~/.desk/STOP_ALL` exists. Exits/stops/daily-DD keep running; the shadow/control book is research-only and not blocked.
  Use: `touch ~/.desk/STOP_ALL` (stop all new buys) / `rm ~/.desk/STOP_ALL` (resume). Alpaca side follows after 21:55 (separate entry).
- **Why:** HANDOFF idea 15: the weekly review already reports the flag, but no code honoured it.
- **Evidence:** staged copy compiled; full suite run against the staged copy (21/21) before an atomic `mv`; live `tests/run_all.sh` 21/21
  (new `tests/test_stop_all.py`); live cron after swap: `run_meme pipeline/risk done rc=0` (21:24:06, 21:24:49, 21:25:06), newpairs runs normal.
- **Params:** 0. **Backup:** `backup_20261020_2123_stopall/` (meme.py, crontab.txt).
- **Revert:** `cp -p backup_20261020_2123_stopall/meme.py meme.py` (via a temp copy + mv), delete `tests/test_stop_all.py`.

## 2026-10-20 21:55 — Risk-rule enforcement audit, Alpaca side + STOP ALL for Alpaca (+ 13 tests)
- **What (fixes, all tightening, no rule loosened):**
  1. `killswitch.py`: on fire -> journal line `logs/alp_kill.jsonl` + `alp_kill.json` FIRST, then explicit `cancel_orders()` and re-read
     open orders until none remain (<= 5 tries, 1 s apart), THEN `close_all_positions(cancel_orders=True)`. Before: one combined call.
  2. `alp_common.kill_active()` FAILS CLOSED: corrupt/unreadable `alp_kill.json` -> True (no Alpaca orders until a human fixes/removes it;
     killswitch logs "FAIL CLOSED"); deleted file -> recovered from the journal. Before: corrupt/deleted -> False (fail open).
  3. `alp_common.submit_block_reason()` re-checked right before EVERY `submit_order` in strategy.py, stocks.py, crypto.py:
     kill active -> block everything; `~/.desk/STOP_ALL` present -> block BUYS (sells/exits still go). Before: kill checked once at start; no STOP_ALL.
  4. `stocks.py` 10%-per-name cap: a held name above 10% of equity is trimmed even inside the 25% rebalance tolerance (before: could drift to ~12.5%).
  5. `stocks.py` no averaging down: no top-up buy of a held name whose price is below its average entry (new names unaffected).
- **Verified holds (no change):** MAX_NAMES=16 (test with 40 listed names -> 16 buys); new buys <= 10% equity; dial < 0.50 -> sleeve to cash;
  -4% threshold uses Alpaca's server-side last_equity (restart-safe). **Flagged, not changed (by design, for Dominic):** TREND and CRYPTO
  re-weight to target, which can add to a losing TQQQ/coin position.
- **Evidence:** staged copies compiled; `tests/test_alpaca_risk.py` 13/13 against staging (8 fail against the old code = the gaps were real);
  live swap after the 21:45 paper run under `.alp.lock`; post-swap: py_compile ok; tests/run_all.sh 34/34; killswitch --dry-run ok (-0.08%), --simulate-drop 5 -> WOULD FIRE (no close); stocks/crypto/strategy --dry-run rc=0 (0 / 0 / 1 tiny TQQQ top-up would-order); next 22:00 kill cron: see STATUS.md.
- **Params:** CANCEL_TRIES=5, CANCEL_WAIT_S=1. **Backup:** `backup_20261020_2155_riskaudit_alpaca/` (alp_common.py, killswitch.py, stocks.py, strategy.py, crypto.py, crontab.txt).
- **Revert:** for each file `cp -p backup_20261020_2155_riskaudit_alpaca/<f> .<f>.tmp && mv .<f>.tmp <f>`; delete `tests/test_alpaca_risk.py`.

## 2026-10-20 23:17 — wallet signal: 215nhc… from COPYABLE to OBSERVE (tightening, no OOS needed)
- **What:** `scan/wallet_signal.py`: `WALLETS` (COPYABLE, exported as `mints` = scan candidate source + rank boost) now only EwJYY4…; 215nhc… moved to `OBSERVE`.
  Its buys are still recorded, but only under `observe_mints`/`observe_tags`, which scan.py/sources.py do not read. `of` = 1.
- **Why:** research says 215nhc is not copyable: I-13 copy test (KNOWLEDGE 22:10, Trader-Research: copy @10 s −13 %/trade, median −42 %, 699 coins/90 d, whale buys move the price, 25 copytrader wallets in the same/next slot; copy edge gone after ~5 s).
  Live impact so far: none of today's 46 meme buys came from the wallet signal (no `wallet` src/field in logs/meme_trades.jsonl); the signal only affected candidate ranking.
- **Evidence:** new `tests/test_wallet_signal_observe.py` (fails on the old code, passes on the new); staged copy compiled + `--dry` against live RPC ok; swap under `.wallet.lock`; tests/run_all.sh 35/35; next cron run writes `observe_mints`.
- **Not changed (for Dominic):** EwJYY4… stays COPYABLE, although the same research (KNOWLEDGE 22:10) rates it NOT copyable (realised −316 SOL, 5/30 winners). The same one-line move would cover it.
- **Backup:** `backup_20261020_2317_wallet_signal_215n/` (scan/wallet_signal.py, sources.py, scan.py, crontab.txt).
- **Revert:** `cp -p backup_20261020_2317_wallet_signal_215n/wallet_signal.py scan/.ws.tmp && flock ~/.desk/.wallet.lock mv scan/.ws.tmp scan/wallet_signal.py`; delete `tests/test_wallet_signal_observe.py`.

## 2026-10-21 00:25 — User-Anweisung: fester Einsatz 10 EUR pro Meme-Trade
- meme.py/newpairs.py: Ticket = min(10 EUR = $11.22, 2% Pool-Liquidität, freies Cash) statt 3%/1.5% x Bank x Dial. book_add-Cap erlaubt das feste Ticket. SL/TP/Max-Positionen/Daily-DD unverändert. Backup: backup_20261021_0024_ticket10eur. Tests grün.

## 2026-10-21 00:28 — User-Anweisung "er soll viel mehr machen"
- Daily-DD-Halt 4% -> 20%; max offene Positionen main 3->6, new pairs 2->3, gesamt 4->8. 10-EUR-Ticket, SL/TP unverändert. Tests angepasst, 35/35 grün. Backup: backup_20261021_0026_moretrades.

## 2026-10-21 00:35 — Wallet-OOS Forward-Tracker CookDoc + panicselling (PAPER, nur Research, keine Live-Aenderung)
- **What:** neuer Tracker `tests/backtest/wallet_oos/tracker.py` (eigene Cron-Zeile `*/2` unter `flock -n .tracker.lock`, Tag `#WALLET_OOS`; bestehende Desk-Crons unveraendert, Backup `wallet_oos/crontab_before_20261021.txt`).
  Erkennt neue Swaps von CookDoc (Dvbv5T…) und panicselling (8k1BPp…) per oeffentlichem RPC ab 2026-10-21 00:17 Berlin, simuliert je neuem Kauf Paper-Kopien +5/+10/+30 s
  mit Exits a30/b60 (Wallet-Verkauf, min. 30/60 min) und Desk-Meme-Regeln mit/ohne 60-min-Time-Stop; Kosten A = meme.py, B = Trader-Check (1 %/Seite + Impact + 0,04 $/Tx), K = min(A,B).
  Preise aus dem pump.fun-Trade-Tape (Bracket, Kauf = Obergrenze, Verkauf = Untergrenze, Wallet-Kauf als CP-Preisimpuls). Report `wallet_oos/reports/wallet_oos.md`.
- **Entscheidungsregel (vorab):** >= 30 neue geschlossene Trades je Wallet; Primaer = +10 s / a30 / Kosten K; positiv nur wenn Ø K > 0, ohne besten > 0, beide OOS-Haelften > 0. Bis dahin "laeuft, nicht entscheidbar". Nichts live.
- **Evidence:** `wallet_oos/tests/test_tracker.py` 37/37 (Kosten + exit_decision gleich meme.py, CP-Formeln, Bracket, Tx-Parser, Sim, Regel, Report); py_compile ok; Dry-Run auf 10 h Historie (Temp-Verzeichnis) ok.
- **Revert:** `crontab -l | grep -v WALLET_OOS | crontab -`; Verzeichnis `tests/backtest/wallet_oos/` kann bleiben (nur Research-Daten).
- **00:40 Nachtrag:** Ticket im Tracker = fix 10 EUR (11,22 $, max 2 % Liquiditaet) wie meme.py seit 21.10. 00:2x (statt 3 % × 99 $); Test prueft Gleichheit mit meme.FIXED_TICKET_USD. Tests 37/37.

## 2026-10-21 00:47 (Eintrag nachgetragen 16:20) — EwJYY4 COPYABLE -> OBSERVE (Verschaerfung)
- **What:** `scan/wallet_signal.py`: EwJYY4… in `OBSERVE` verschoben; `WALLETS` (COPYABLE) ist jetzt leer, `mints` bleibt leer (kein Scan-Kandidat und kein Rank-Boost aus Wallet-Signal mehr).
- **Why:** Trader-Research (KNOWLEDGE 2026-10-20 22:10): realisiert −316 SOL, 5/30 Gewinner -> nicht kopierbar. Regel wird nur verschaerft.
- **Evidence:** `tests/test_wallet_signal_observe.py` OK, py_compile ok, Cron-Lauf 16:19 fehlerfrei.
- **Backup/Revert:** `backup_20261021_0047_wallet_signal_ewjyy4/`.

## 2026-10-21 17:15 — Dashboard-Redesign "SAVIP" (GROKBOT DESK, nur Layout/Design)
- **What:** neues Modul `dash_savip.py` (Desk-Floor-Canvas-Pixel-Szene, Balance-Chart LIVE/1H/1D/1W Meme+Alpaca, Holdings mit Sparklines + Tap-to-Expand, Analysis-Panel aus letztem Scan, Activity-Feed). `build_dashboard.py` ruft `_sv.assemble()`/`_sv.page()` mit Fallback auf altes Layout; alte Sektionen eingeklappt darunter. `dash_charts.py alp_history`: Alpaca-Periode 1M+1H (400) ersetzt durch 1D/5Min, 1W/1H, 1M/1D, soft-fail. Keine Trading-Logik geaendert.
- **Evidence:** Testbuilds "errors: none", Headless-Render 390x844 + 1280x800 ohne Seiten-Console-Errors; Live-Cron-Build 17:07 ok; Drive-Kopie ~243k Zeichen (<600k); kein [redacted] auf der Seite; Site weiter passwortgeschuetzt (401 anonym). Box-Reboot ~17:09: cron-Paket fehlte -> neu installiert, Crontab aus Backup (identisch mit Stand 16:47) wiederhergestellt.
- **Backup/Revert:** `backup_20261021_1649_dashboard_savip/` (build_dashboard.py, dash_charts.py, herenow_publish.py, dashboard/) zurueckkopieren; `dash_savip.py` kann bleiben.

- 2026-10-21 17:58 CEST — Dashboard SAVIP v2: canvas desk floor v2 (dash_scene.js: terminal wall monitor, venue tile/banners, 6 two-monitor stations, chief ghost head desk, TOP RUNNER rocket, WHALE RADAR dish, LOCAL TIME Berlin clock, DAY x · 6 RULES board, rack/sofa/plants, event bubbles); real coin logos (dash_logos.py → chart_cache/logos 64px WebP, DexScreener/pump.fun/parqet, initials fallback, here.now only, stripped from Drive copy; publisher stage_logos caps 150 files/1 MB); 1:1 CSS pass vs reference frames; compact side candles (svg_mini) keep Drive copy ~303k chars. Backup: backup_20261021_1722_dashboard_savip_v2/. Revert: copy backup files back, or DESK_SCENE_V1=1 / remove dash_scene.js for the old scene; DESK_NO_LOGOS=1 disables logos.

- 2026-10-21 18:25 CEST — Dashboard SAVIP v3 (floor zoom): whole desk tile is tappable (white hover outline, press scale); tile grows from its grid position into the floor panel (420 ms ease, others fade, header switches to "Desk floor / main screen: …"); "← Zurück" pill top-left reverses it. In single view every monitor is tappable (wall = desk's main coin candles + volume; desk monitors = real holding sparkline / candle volume / candle-return heatmap / open-position P&L) and zooms into a full-panel chart re-rendered at target resolution; second Zurück returns to grid. Pointer-up taps (no 300 ms delay), swipe left/right = next desk, Esc = back, view + monitor kept in sessionStorage across data refresh/reload; bottom arrows removed (not in the clip). Files: dash_savip.py, dash_scene.js (v3). Backup: backup_20261021_1812_dashboard_savip_v3/. Revert: copy dash_savip.py + dash_scene.js back from that backup.

- 2026-10-21 18:55 CEST — Dashboard SAVIP live: clock ticks every second (Berlin, CEST/MEZ, colon pulse, minute roll); "aktualisiert vor Xs" + "meme live · Xs / alpaca · Xs" chips tick; open meme positions re-marked in the browser from DexScreener tokens/v1 (public, keyless, CORS *, every 8 s, no cookies/referrer) with the server formula value = qty x price, P&L = value - cost -> holdings rows (count-up + green/red flash, live sparkline tail), desk tiles, main-screen coin, floor floats, wall-monitor last candle / new candle per bar, live meme equity line + pulsing end dot; floor bubbles on new trades (data.json evt) and >=5 % moves. data.json is fetched only when the new tiny v.json (same publish, no extra here.now version) changes; v.json polled every 10 s. Polling pauses on hidden tabs, resumes instantly; failures keep last data + grey "offline" header dot. Page reload every 60 s replaced by reload-on-new-code (desk-ui hash) and the publisher now uploads index.html immediately when that hash changes. Alpaca stays server-side (no keyless CORS quote source; extra 30 s live.json publisher rejected: here.now free plan = 60 publishes/h, we already use ~42/h). Files: dash_savip.py, dash_scene.js, herenow_publish.py. Backup: backup_20261021_1829_dashboard_live/. Revert: copy those three files back from it.

## 2026-10-21 19:12 CEST — QUANT dial: FRED fetch fix + hourly catch-up (data plumbing only, 0 risk params)
- **Root cause:** (1) 06:00-NY dial run missed (box paused 02:16-16:16 Berlin) -> dial 31 h old -> Judge blocked. (2) Manual re-run 19:05: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<series>` (URL correct) answered **HTTP 200 text/html "Site Maintenance | St. Louis Fed"** (also api.stlouisfed.org / alfred); the curl fallback only fired on HTTP errors, so the HTML went into `pd.read_csv` -> "Expected 1 fields in line 5, saw 3" -> liquidity/VIXCLS/BAMLH0A0HYM2 DEGRADED -> meme 0.25.
- **What:** `quant_dial.py fred()`: response validated (non-CSV / wrong columns -> error), retries, curl; then same series from the original publisher: VIXCLS = Cboe `VIX_History.csv` CLOSE (10-16 19.99 = FRED value), WALCL/WTREGEN = Fed H.4.1 DDP `RESPPA_N.WW` / `RESPPLLDT_XAW_N.WW`, RRPONTSYD = NY Fed ON RRP API (daily sum, USD->bn); net liquidity 10-14 5872.1 / 09-16 5864.1 bn = identical to yesterday's FRED-based dial. Then FRED API (only if `FRED_API_KEY`), then last good cache `dial_cache/<series>.csv`. Ages still from observation date, MAX_AGE_H and dial rules unchanged -> stale/red stays red. New json keys `sources`, `fetch_notes`; `run_dial.sh` log line shows fallback sources. Fixed: FRED '.' missing values parse.
- **Catch-up:** new `dial_catchup.sh`, cron `20 * * * *` (#DESK): runs `run_dial.sh` (flock .dial.lock) if newest dial > 20 h, today's file missing after 06:30 NY, or newest dial has fetch errors; skips 05:50-06:30 NY. 06:00-NY line unchanged.
- **Evidence:** re-run 19:11: meme 0.75 / stocks 0.75 / crypto 0.5, degraded=[BAMLH0A0HYM2] only (no HY-OAS 2nd source; credit was red yesterday too, +0.63; not a meme gate). VIX 17.31 (10-20) green, liquidity +7.9 bn green. Judge gates pass (age 0 h, no meme input degraded, meme >= 0.50); live cron 19:10:05 picked QUARTZ. New `tests/test_quant_dial_fetch.py` (6); `pytest tests --ignore=tests/backtest` 41 passed; `tests/run_all.sh` 41 OK. Bare `pytest tests` fails at collection in tests/backtest/staging (duplicate basenames, missing `_iso`) — pre-existing, not touched.
- **Backup:** `backup_20261021_1908_dial_fred_catchup/` (quant_dial.py, run_dial.sh, README.md, CHANGELOG_research.md, KNOWLEDGE.md, dial/*.json, crontab.txt).
- **Revert:** `cp -p backup_20261021_1908_dial_fred_catchup/{quant_dial.py,run_dial.sh,README.md} ~/.desk/`; `crontab backup_20261021_1908_dial_fred_catchup/crontab.txt`; delete dial_catchup.sh, tests/test_quant_dial_fetch.py, dial_cache/.

## 2026-10-21 19:26 — I-18 twin-buy gate LIVE (approved by Dominic 19:24) + V-01/I-18 shadow fields per main pick
- **What:** `meme.py`: new `pick_shadow_hook(top)` right after `[JUDGE] PICK` (before SIZE). Constants `I18_GATE_ENABLED = True`, `I18_BLOCK_SHARE = 0.50`, `I18_MIN_BUYS = 5`, `PICK_SHADOW_TIMEOUT_S = 6`.
  Gate: ONE pump.fun swap-api call (100 newest trades before the pick, hard timeout 6 s in a thread). Skip the pick if ≥ 50 % of the buys of the last 15 min have a "twin" (same second, same SOL amount to 4 dp, other wallet) and there are ≥ 5 buys.
  Log: `[JUDGE] skip … I-18 twin-buy share …`; shadow book entry `main:blocked:i18`. **Fail-open:** timeout, error or no data never block (note in the shadow log).
  New `pick_shadow.py` (detached child via `timeout 60`, never delays the buy) writes one line per final pick to **`~/.desk/logs/pick_shadow.jsonl`**:
  i18_twin_share, i18_n_buys, i18_would_block, blocked, note, V-01 v01_n_top/n_known/n_fresh/would_block (≥ 9/12 wallets < 24 h; public Solana RPC only, **shadow only, never blocks**).
- **Why / evidence (OOS passed):** 161 random pump.fun graduations 2026-09-20..10-20, decision at migration + 15 min. Walk-forward 3/3 weeks better (ret sum −21.9 → −12.3, dd80 lower every week).
  Untouched holdout = last 7 days, n = 21: 5 blocked, all 5 ≈ 0 (dd80 100 %); kept −11.6 → −6.5; dd80 38 % → 19 %. Threshold 0.504 from pre-holdout.
  Wallet-age check: the effect holds even with 0 fresh top buyers (bots/herds, not fresh bundles). Report `tests/backtest/reports/youtube_ideas.md` (I-18 FINAL), code `tests/backtest/meme/i18_bundles.py`.
  Limits: small holdout, 6 variants tested, ≤ 100 trades per window. The gate only tightens (fewer buys); no risk rule loosened.
- **Tests:** new `tests/test_i18_gate.py` (11): block at ≥ 50 %, no block < 50 %, no block with < 5 buys, timeout (fake 10 s, gives up after ~1 s) and error do not block, gate off never blocks, Popen failure never raises, hook sits before SIZE, twin feature math, error → null fields logged. All 11 pass against staging; tests/run_all.sh 52/52.
- **Swap:** staged copies → py_compile → tests → `pick_shadow.py` mv, `meme.py` mv under `.gate.lock` at 19:26:21.
- **Backup:** `backup_20261021_1924_i18_shadow/` (meme.py, crontab.txt).
- **Revert:** gate off only: set `I18_GATE_ENABLED = False` (copy → py_compile → mv). Full revert: `cp -p backup_20261021_1924_i18_shadow/meme.py .meme.py.tmp && flock .gate.lock mv .meme.py.tmp meme.py`; optionally delete pick_shadow.py + tests/test_i18_gate.py.

## 2026-10-21 19:52 CEST — USER ORDER (Dominic 19:34 + 19:37): rule 7 first-candle launch pump + rule 8 bot-wash pattern (tightening only)
- **Trigger:** KIMCHI / SOL ("The Yellow Bull", mint AAE28LvD…pump, pool ELpV9s8G…): Judge PICK 19:30:06, $11.21 at 0.0001097; peaked +30 % at 19:33; liquidity pulled 19:33 (-98 % in one candle) -> stop-loss SELL 19:34:13 at 2.03e-6, **pnl -11.05 $ (-99 %)**. Launch 19:14:00: first 1m candle +4459 % (3.02e-6 -> 1.38e-4, whole curve bought + graduated in minute 1) = 100 % of the rise to the entry-time ATH, 13 % of volume; afterwards a 1s sawtooth in a 5-10 % band (trade every second, ~20 near-identical -3..-4 % drops per 2 min, autocorr -0.25) until the rug 19 min after launch.
- **What:** new `rugpattern.py` (pump.fun swap-api candles, keyless, 0 GeckoTerminal calls, cache `scan/rugpattern_cache.json`: launch candle permanent, 1m 60 s, 1s 20 s; <= 20 calls/run, budget used -> "not judged", never "allowed").
  - **rule 7 · first candle**: main: skip if first 1m candle from launch >= +1000 % AND >= 50 % of rise to ATH so far; newpairs: skip if >= +150 %. No data: newpairs SKIP ("no first-candle data"), main ALLOW + log ("rule 7 n/a … -> allowed", e.g. coin older than the 1000-candle 1m history).
  - **rule 8 · bot-wash pattern** (last 120 1s candles within 1 h): micro-wash (alternation >= 0.65, size CV <= 0.70, band <= 3 %, efficiency <= 0.15) or sawtooth (density >= 0.95, >= 15 drops > 1.5 % with CV <= 0.30, autocorr <= -0.15, efficiency <= 0.10). No data -> allow + log.
  - meme.py Judge: after judge_metrics passes, before RugCheck (`rugpattern_fails`); reason `judge: rule 7 · first candle +X% …`; single fails go to the shadow book as `main:gate:judge: rule 7 first candle` / `rule 8 bot-wash pattern` (gate_key extended). newpairs.py `safety()`: after the cheap gates, before RugCheck. Dashboard Activity: "Dropped X · rule 7 · … · MEME / NEW PAIRS".
- **Impact (in-sample, entry-time data):** rule 7 real 46 closed main trades -> blocks 12 (-12.68 $, avg -14.3 %/trade, 3 winners +2.64 $) vs kept avg -2.6 %; shadow 180 -> blocks 53 (-81.03 $, avg -29.5 %) vs kept -11.7 %. 8 real trades had no launch minute in 1m history (allowed). Newpairs: the 4 new-pairs trades (first candle +57..+78 %) not blocked. Rule 8: of 55 trades with 1s coverage flags KIMCHI (-11.05 $) + 14 flat control-book shadows; no winner flagged; live sample 79 coins -> 22 micro-wash bot-farm coins (mostly already Judge-rejected), sawtooth only KIMCHI (+JOCAT 2/30 windows).
- **Params:** new only (R7_MIN_PCT 10.0, R7_MIN_SHARE 0.50, NP_R7_MIN_PCT 1.50, rule 8 constants above); no existing threshold changed. In-sample calibration -> Backtest OOS request `shared/inbox_backtest_firstcandle.md`; data `research/firstcandle_20261021/`.
- **Evidence:** `tests/test_rugpattern.py` (13: KIMCHI fixture blocked by rule 7 + rule 8, organic coins pass, graduation-style pump with later growth passes main, missing-data policy, call budget, newpairs skip before RugCheck); `pytest tests --ignore=tests/backtest` 65 passed; `tests/run_all.sh` 65 OK; `meme.py dry` / `newpairs.py dry` rc=0; dashboard build "errors: none".
- **Note:** daily-DD halt fired 19:35 (-23.15 % vs 20 % limit, after KIMCHI/PLAZA) -> no new entries today in either sleeve; rules take effect on the next non-halted run.
- **Backup:** `backup_20261021_1945_firstcandle_wash/` (meme.py, newpairs.py, scan.py, dash_savip.py, build_dashboard.py, README.md, CHANGELOG_research.md, KNOWLEDGE.md, crontab.txt, tests_snapshot/).
- **Revert:** `cp -p backup_20261021_1945_firstcandle_wash/{meme.py,newpairs.py,dash_savip.py} ~/.desk/`; delete rugpattern.py, tests/test_rugpattern.py, tests/fixtures/kimchi_candles.json.

- 2026-10-21 20:17 USER ORDER (Dominic: "hebe daily limit auf"): meme daily drawdown halt switched OFF (meme.DAILY_DD_ENABLED=False; affects main + newpairs; today's 19:35 halt released). SL/TP, 10 EUR ticket, position caps, rule 7/8 unchanged. Tests force it ON. Revert: set DAILY_DD_ENABLED=True. Backup backup_20261021_2017_no_daily_limit/

## 2026-10-21 20:24 CEST — USER ORDER (Dominic 20:19 "der bot soll wieder mit 100€ anfangen"): paper meme bank reset to 100 € = $112.15
- **Old bank:** epoch 1 (started 2026-10-20, $100.00) ended 20:21 at **$73.29** (realized −$26.71, 77 closes, 34W/43L). Bank before the reset closes was $73.62 with 2 open positions.
- **Open positions:** closed at the DexScreener mark with the normal sim exit (fees and slippage), reason `reset: bank reset to 100 EUR (USER ORDER …)`: ✋ / SOL −$0.31, Pokecity / SOL −$0.35. The 24 h cooldown entries these closes created were removed from `meme_cooldown.json` (reset ≠ loss signal).
- **New epoch 2:** `bank.json` start_capital 112.15 (start_eur 100, EURUSD 1.1215), started_at 2026-10-21T20:21:21+02:00, `epochs[]` holds the epoch 1 summary. The closed book was archived to `archive/meme_epoch1_20261021_2021.json` (not deleted) and `closed` emptied. `history.csv` moved to `archive/history_epoch1_20261021_2021.csv`; the new history starts at 112.15. Shadow books are untouched.
- **Risk:** risk_state.json and the journal record `{"day_open_equity":112.15,"halted":false,"epoch_reset":…}`. `meme._journal_today` now lets an `epoch_reset` record replace the day's sticky halt. Nothing else does, so the sticky-halt rule is otherwise unchanged. `DAILY_DD_ENABLED=False` (user 20:17) stays off. FIXED_TICKET_EUR 10, MAX_OPEN 6, TOTAL_MAX_OPEN 8, NP_MAX_OPEN 3 and the stops are unchanged (verified by diff).
- **Dashboard:** `build_dashboard.py` adds bank start_eur, epoch, started_at, started_label and previous. `dash_savip.py` shows the balance "since reset (100 €, 21.10. 20:21)" and a Vorperiode-1 note. Published 20:22, and the widget feed shows balance 112.15, start 112.15, P&L 0, 0 open.
- **Files:** new `bank_reset.py`. Changed: meme.py, build_dashboard.py, dash_savip.py, bank.json, meme_positions.json, history.csv, risk_state.json, meme_cooldown.json, plus a new test `test_epoch_reset_record_replaces_sticky_halt`. Tests: `pytest tests --ignore=tests/backtest` 66 passed, `tests/run_all.sh` OK.
- **Backup:** `backup_20261021_2020_bank_reset_100eur/`. **Revert:** restore the listed files from the backup (incl. logs/risk_state.jsonl and history.csv), delete bank_reset.py, the archive/*epoch1* files and the new test.

## 2026-10-22 11:00 — NOTE (no code change): I-18 evidence correction
- Re-check found the I-18 OOS result (WF 3/3, holdout 5/5) is driven by spoof-pool price prints in the pump.fun swap-api (27 of 33 blocked coins). On clean coins there is no effect. Live gate is unchanged (still True; 41 picks, 0 blocked so far). Decision on switching it to shadow (I18_GATE_ENABLED = False) is with Dominic. Details: tests/backtest/meme/d0x_progress.md (Schritt 0b).

## 2026-10-22 12:30 — NOTE (no code change): the I-18 evidence correction of 11:00 is WITHDRAWN
- On-chain check: the "spoof" prices are real prices of the migration pool (pool balances after the tx match the API price within 5–7 %). The I-18 OOS evidence stands as originally logged; a clean re-test with a dust filter is running (tests/backtest/meme/clean_progress.md).

## 2026-10-22 13:36 — OPS (no trading-rule change): desk moved to GitHub Actions (d0mvx/trading-desk)
- **Live desk = GitHub Actions** (workflow `desk-live`, ~5 h 50 min per run, self-dispatch handover + 6-h schedule, concurrency `desk-live`). `gh/desk_loop.py` runs `gh/crontab.gh` = the former box #DESK lines 1:1 (Berlin time). Paper only, unchanged.
- **Box:** the 15 trading/publish cron lines are commented `#GHCUT# ` (watchdog + #WALLET_OOS stay). The box holds only a synced **state copy**: `#GHSYNC` cron pulls branch `state` every 5 min (`pull_state.sh`) and pushes approved CODE to `main` every 10 min (`push_code.sh`, secret scan + pytest gated). Box bots must NOT write state files directly (overwritten every 5 min); trading code changes go through Backtest -> ~/.desk code -> push_code.
- **State:** branch `state`, committed every 5 min and on job end; allowlist `deploy/state_manifest.txt`; every commit secret-scanned. Gate file `GH_LIVE` on `state` (no file = nothing runs on GitHub).
- **Code changes for GitHub (backward-compatible, env first, local files as fallback):** alp_common.py, build_dashboard.py, meme.py, herenow_publish.py, run_dial.sh, run_strategy.sh (backup `backup_20261022_0339_github/`); run_meme.sh caps the pipeline dashboard build at 120 s after a hung build blocked the meme pipeline 12:00–13:10 (`backup_20261022_1310_buildtimeout/`); tests/test_meme_stops.py cadence test also accepts gh/crontab.gh (`backup_20261022_1337_test_cadence_gh/`).
- **Known limits:** GeckoTerminal answers part of the runner's calls with 429 (shared GitHub IPs) -> main scan sees fewer pools (60–100 vs ~130) and no GT "extras"; DexScreener, pump.fun, Alpaca, here.now work. Handover gap ~1–2 min.
- **Revert:** `~/.desk-sync/tools/box/rollback.sh` (removes GH_LIVE, cancels runs, pulls final state, restores the #GHCUT# lines).

## 2026-10-22 15:10 — USER ORDER (Dominic 14:53): meme scan data source GeckoTerminal -> DexScreener (data source only, NO rule change)
- **Why:** on the GitHub runner GeckoTerminal answers with 429 (shared IPs): 13:40–15:10 runner scans median 80 pools, median 1 candidate (28 of 82 scans with 0), 199 429/budget errors; box level was ~145 pools / ~10 candidates.
- **New path (`scan.py` ds_collect, `sources.py` ds_universe/ds_to_gt/gt_overlay/gt_enrich):** universe = pump.fun frontend-api-v3 feeds (6 calls: live, active x2, curve leaders, NEW graduated-active x2) + DexScreener profiles/boosts/top boosts/ads/community-takeovers + search pumpswap/pumpfun -> mints -> DexScreener `/tokens/v1` (30 mints/call, <= 12 calls; ~4 in practice) -> one pump.fun/PumpSwap SOL pair per mint, mapped 1:1 into the GeckoTerminal pool shape (liquidity, volume, buys/sells h1/h6/h24, mcap/fdv, pair age, price, SOL price, price change m5/h1/h6/h24).
- **Still on GeckoTerminal (no exact DexScreener equivalent):** txns m15 (buys/sells), unique buyers (h1/h6/h24), price change m15/m30 (and a price-change window DexScreener omits). Fetched with ONE `/pools/multi` call (<= 30 pools) only for pools that already pass every other SCAN gate (+ pump.fun coins DexScreener does not index yet). Missing GT data = the same gate fails ("buys m15 n/a"), never a pass; such pools are not counted as one-gate shadow misses. Judge OHLCV (1 call) and the pre-buy GT fallback are unchanged. GT calls per scan: 7 -> 1.
- **Unchanged:** all filter thresholds, risk rules, ticket size, rules 1–8, Judge, RugCheck, cooldown, stale rule, ranking. Old path kept: `DESK_SCAN_SOURCE=geckoterminal` (and automatic fallback when DexScreener returns nothing).
- **Parity (box, dry, same moment, 4 runs):** same pools fetched from both sources -> identical pass/fail decision 98/98, 102/102, 101/101, 106/106; full universes: old candidates also found by the new path 12/12, 14/14, 13/15, 13/15 (misses: 2 coins only in GT's tx-sorted lists / a DexScreener search page that changed between calls); new-only candidates 6, 4, 0, 3 (coins outside the old universe or a GT m15 change between the two calls). Differences among rejects only: DexScreener marketCap/liquidity glitches on wash pools, non-SOL pairs. Pools/scan new ~95–100 (the ~30 missing vs GT lists are GT-list rejects; none passed).
- **Tests:** `tests/test_ds_scan_mapping.py` + fixture `tests/fixtures/ds_gt_parity.json` (field mapping 1:1, overlay only GT-only fields, same decision on GT vs DS data, 1 GT call, GT failure never creates a pass, thresholds unchanged). Backup: `backup_20261022_1457_dexscreener_scan/`.
- **Deployed 15:07 (push_code -> main 0277450), runner restart 15:09:42** (cancel; pending scheduled run 39780391612 took over with `ref: main`): last old tick 15:10, first new tick 15:12 (1 minute tick missed), state saved by the job-end step. **Runner 15:12–15:27 (16 scans):** pools median 99 (96–106), candidates median 16 (13–20, 0 empty scans; before 13:40–15:10: median 80 pools, median 1 candidate, 28/82 empty), GT calls 1/scan, 0 429/budget errors (before: 199). First Judge buy on the runner: CODEX 15:25 (dip entry, RugCheck ok, ticket $11.21).

## 2026-10-22 18:15 — USER ORDER (Dominic 17:58): SELF-LEARN — the meme bot learns from its own closed trades (PAPER ONLY)
- **Context:** Backtest, Memecoin Analyse and Trader Check bots are STOPPED. From now on trading-rule changes come ONLY from (a) the self-learner below with its gate, or (b) direct user orders. No desk code path waits for a Backtest approval (only comments referenced it; `box/push_code.sh` / `box/pull_state.sh` comments updated).
- **New `learner.py`** (runs on the GitHub runner via `gh/crontab.gh`: `learner.py tick` every minute, learns only when due = 30 min since last run OR >= 10 new closed sells). Journal = real closed trades epoch 1 (`learner_seed_epoch1.json`, from archive/) + epoch 2 (`meme_positions.json`) + shadow book (`logs/shadow_trades.jsonl`), each with entry features (liq, mcap, vol24, vol/liq, age, buys/buyers h1, buyers/buy, buy/sell m15, pc h1/m5, rule-7 first-candle pct/share, hour, dial, entry type, narrative for newpairs) joined from the entry-minute scan files; new buys/shadows now store `feat` at entry (`meme.py`, `shadow.py`).
- **Allowlist (16 params, hard floor/ceiling):** pumpswap liq_min 8k–60k, mcap_min 25k–150k, mcap_max 1M–8M, vol24_min 25k–250k, max_vol24_to_liq 10–40, age_max_h 12–72, age_min_h 0.25–3; min_buys_h1 10–60, min_buys_m15 2–10; J_MIN_BUYERS_H1 40–250, J_MIN_BUYERS_PER_BUY 0.2–0.6, J_MIN_BS_M15 1.0–3.0, J_PC_H1 low 5–60 / high 100–300; R7_MIN_PCT 3–10, R7_MIN_SHARE 0.3–0.8. **Never touched (forbidden list):** paper mode, fixed 10 € ticket, max positions 6/3/8, stop-loss / take-profit / exit structure, daily limit (off), RugCheck/I-18/security, Alpaca, kill switch, cooldown, judge budget.
- **Gate:** TIGHTEN only if the pocket that the new value would block has >= 15 trades, mean <= -5 % and mean + 1 SE < 0, AND the same on the newest 30 % of trades (time-ordered holdout, >= 5 there). LOOSEN only if the shadow trades blocked by exactly that gate within the new value have >= 20 samples, mean >= +5 % and mean - 1 SE > 0, AND the same on the holdout. Max 1 change per param per 24 h, step <= 25 % (5–25 % candidates), floors/ceilings, max 2 changes per run. **Auto-revert:** after 48 trades post-change, if their expectancy is worse than the (>= 15, up to 48) trades before -> revert + log.
- **Output:** `learner_overrides.json` (state; applied at import by scan.py / meme.py / rugpattern.py via `learner.apply`, invalid/forbidden/out-of-bound values ignored), `learner/report.json` + `learner/journal.json`, `logs/learner.log`, `logs/learner_changes.jsonl`; the box mirrors each change into this file + shared/KNOWLEDGE.md tagged SELF-LEARN with evidence (`learner.py publish` after `pull_state`). Dashboard: new panel "Lernt dazu" (last 5 changes in German + trades analysed).
- **Kill switch:** `LEARNER_ENABLED = True` in learner.py; env `LEARNER_ENABLED=0` overrides (no learning, no overrides applied -> code values).
- **Dry run on epoch 1 + epoch 2 (18:09):** 114 real closed trades (106 main, all with features; 8 newpairs), 688 closed shadow trades. Main overall n=106, Ø -4.5 %/trade, win 28 %, 39 fast stops (<10 min), 1 rug. **Proposals: 0.** Tighten pockets next to the current thresholds are too small (e.g. mcap_min 40k->44k n=4, J_MIN_BS_M15 1.2->1.25 n=14, ->1.3 n>=15 but Ø -2.6 % not clearly negative, buyers/buy 0.25->0.28 n=4, J_PC_H1 high 300->270 n=5, age_min 0.25->0.3h Ø +1.1 %); loosen evidence too thin (would-be shadows in step: J_MIN_BS_M15 1.1 n=7, R7_MIN_SHARE 0.55 n=3, buyers/buy 0.22 n=2, others 0–1). Loss clusters exist but far from any threshold (bins n=21: buyers_h1 56–222 Ø -22 %, pc_h1 78–125 % Ø -24 %, liq 25–31k Ø -20 %, buys_h1 83–353 Ø -19 %, mcap 19–58k Ø -17 %, hour 0–5 Berlin Ø -11 %) -> not reachable with one <= 25 % step; the learner re-checks every cycle.
- **Tests:** `tests/test_learner.py` (17: tighten pass, min samples, holdout, not-negative, loosen pass / <20 / negative / holdout / other gate, step bounds + floor/ceiling, forbidden params, apply bounds + tuple param, kill switch, live cycle + 24 h cooldown, dry writes nothing, auto-revert, no revert <48 or when better, max changes per run, code values captured). Full suite 91 passed.
- **Backup:** `backup_20261022_1804_selflearn/`. **Revert:** set `LEARNER_ENABLED = False` (or env 0) -> code values; full revert = restore scan.py, meme.py, rugpattern.py, shadow.py, build_dashboard.py, dash_savip.py from the backup, delete learner.py, learner_seed_epoch1.json, tests/test_learner.py, and the learner line in gh/crontab.gh.
- **18:22 fix (SELF-LEARN, no rule change):** first runner start 18:13 did not learn: the inner run lock in `learner.tick()` was the same file `.learner.lock` that the cron line already holds via `flock -n` -> every tick skipped silently. Inner lock is now `.learner_run.lock`; test `test_tick_runs_under_the_cron_flock` added; kill-switch test no longer writes to the real logs/learner.log. Suite 92 passed.
2026-10-22 18:30 | SELF-LEARN deploy verified: runner run 39813379887 (code e4bb769), first live cycle 18:24 CEST: 106 main / 696 shadow, mean -4.5 %, changes [] reverts []; learner_overrides.json + learner/report.json on state branch.

## 2026-10-22 19:57 — SELF-LEARN tighten: meme.J_MIN_BS_M15 1.2 -> 1.45 (learner.py, gate passed, no user order)
- verschärft: 45 Trades im Bereich 1.2–1.45 Ø -5.6% (Gewinnquote 22%), neueste 30 %: 19 Trades Ø -3.3%
- evidence: {"pocket": {"n": 45, "mean": -0.0559, "se": 0.0549, "win": 0.222, "sum": -2.5133}, "kept": {"n": 69, "mean": -0.0313, "se": 0.0453, "win": 0.333, "sum": -2.1596}, "holdout_pocket": {"n": 19, "mean": -0.0328, "se": 0.0814, "win": 0.263, "sum": -0.6234}, "holdout_kept": {"n": 16, "mean": 0.0257, "se": 0.1024, "win": 0.375, "sum": 0.4116}, "holdout_from": "2026-10-22T05:23+02:00"}
- override in learner_overrides.json (state); auto-revert after 48 trades if worse; kill switch LEARNER_ENABLED=0

## 2026-10-22 22:05 — USER ORDER (Dominic 21:44): rule 9 anti-chase + rule 10 dump candle (rugpattern.py, tightening only)
- **Order:** "er tradet ständig rugs welche man schon vorher mit bloßem auge sieht und traded viel nach dem hype und volumen" -> analyse epoch-2 trades, add tightening filters only (ticket, stops, TPs, max positions, paper-only unchanged).
- **Data:** epoch 2 (since 21.10. 20:21 CEST), closed trades with GeckoTerminal 1m candles before entry: 67 real main, 203 shadow main, 264 shadow control (+4 real / 17 shadow newpairs via pump.fun 1m). In-sample calibration, PnL in EUR at the 10 EUR ticket.
- **rule 9 · chase (main + newpairs):** price now vs close 15 min ago >= +100% (`R9_MAX_RUN15 = 1.0`, `NP_R9_MAX_RUN15 = 1.0`) -> skip.
  real: blocks 15 = 14 losers (-38.9 EUR) / 1 winner (SHAVCOIN +8.9 EUR), net -30.0 EUR; kept 52 avg +0.2 %. shadow main 17 (13 L -33.7 / 4 W +14.6, net -19.1); control 11 (10 L / 1 W, net -18.0). Thresholds +60/+80 % added more winners, +150 % missed half the losers.
- **rule 9 · young pool (main only):** < 25 active 1m candles in the last 60 min AND price vs 30 min ago >= +100% (`R9_YOUNG_N60 = 25`, `R9_YOUNG_MAX_RUN30 = 1.0`). Incremental to the above: real 7 (5 L -22.9 incl. WORLDCOIN -98 % / 2 W +10.8, net -12.1); shadow main 21 (18 L / 3 W, net -30.9); control 10 (7 L / 3 W, net -17.5).
- **rule 10 · dump candle (main + newpairs):** a 1m candle in the last 10 min with open->close <= -20 % (`R10_MAX_RED1M = 0.20`, `R10_WIN_S = 600`, `NP_R10_MAX_RED1M = 0.20`). Incremental: shadow main 58 (38 L -147.5 / 20 W +93.7, net -53.8), control 28 (21 L / 7 W, net -72.1); real only 5 (2 L -10.1 incl. umi / 3 W +16.8, net +6.7 = costs on the real sample, kept because the 91-trade shadow evidence is clearly negative).
- **All three together:** real 27 blocked = 21 L (-71.9 EUR) / 6 W (+36.4 EUR), net -35.5 EUR; kept 40 trades avg +1.6 % (vs all 67 avg -4.3 %). Shadow main 96 (69 L / 27 W, net -103.9), control 49 (38 L / 11 W, net -107.6).
- **Not added (no evidence):** volume fade after the volume peak (blocked trades were better than kept), above-60-min-low, biggest 1m green candle, wick range. umi (-99 %) was a flat chart + post-entry liquidity pull: not visible in pre-entry candles.
- **Data / budget:** same pump.fun 1m candles as rule 7 (per-process memo, 0 GT calls; cache `r9` in scan/rugpattern_cache.json, 60 s). No data -> allowed + logged (both sleeves); call budget used -> "not judged" (no buy).
- **Learner:** allowlist `rugpattern.R9_MAX_RUN15` (max, 0.60–1.0) and `rugpattern.R10_MAX_RED1M` (max, 0.12–0.20); ceiling = shipped value -> it can only tighten. Features `run15`, `red10` from the cache. Young-pool rule is not in the allowlist (two-condition rule).
- **Tests:** `tests/test_rugpattern_chase.py` (10), test_learner CUR updated. Suite: 102 passed.
- **Revert:** restore rugpattern.py / learner.py from git (commit before this one), delete tests/test_rugpattern_chase.py.

## 2026-10-23 17:46 — USER ORDER (Dominic 2026-10-23 17:43, "Beides umsetzen"): chase cooldown 60 min + profit lock
- **Why (diagnosis 23.10. 17:4x, epoch 2, in-sample, USD):** after the rule 9/10 deploy (22.10. 22:08) 8 tokens were blocked by rule 9/10,
  6 of them were bought minutes later anyway (Kimchi +5.93, Bear -5.74, PUMP -3.72, Martin -0.99, McNugget -1.40, 1/SOL newpairs -2.36 = -8.28).
  16/71 main trades reached peak >= +15% and still closed at a loss (-26.36; trail -25% from peak arms at +15% -> can exit ~-14%).
- **1. Chase cooldown:** a rule 9 (chase) / rule 10 (dump candle) block puts mint + pool (main) or mint + bonding curve (new pairs) on a
  `rugpattern.CHASE_COOLDOWN_MIN = 60` min cooldown in `meme_cooldown.json` (state branch -> survives ticks + runner restarts).
  `meme.chase_cooldown()`; `scan.cooldown_add(..., minutes=)` never shortens a longer running (24 h) cooldown. Reject text shows the reason.
- **2. Profit lock:** `meme.LOCK_TRIGGER = 0.15`, `meme.LOCK_FLOOR = 0.05`: once peak (vs entry fill) >= +15% the effective stop is
  max(trailing stop, entry fill x 1.05) -> exit "profit lock: ...". Same `exit_decision` for main, new pairs (both tiers) and shadow;
  per-plan override keys `lock_trigger`/`lock_floor`. Open positions: uses their stored peak_price (lock applies at once if peak >= +15%).
  NOT in the learner allowlist (stop parameter; changed only by this direct USER ORDER). Hard stop, trail, TPs, ticket, max positions unchanged. Paper only.
- **Expected (in-sample, unverified on minute paths):** cooldown +8.28 $ on 6 trades since deploy; profit lock up to ~+26 $ over the epoch
  (16 trades), minus winners that dip to +5% after +15% and then run (not measurable without minute candles).
- **Tests:** tests/test_profit_lock_cooldown.py (11); _iso.py redirects scan.COOLDOWN_FILE. `pytest tests --ignore=tests/backtest`: 113 passed.

## 2026-10-23 19:30 — USER ORDER (Dominic 2026-10-23 19:15, corrected 19:23): meme bank reset, epoch 3 = 1 SOL in EUR — STANDING RULE
- **Standing rule:** every meme bank reset starts at the live price of 1 SOL in EUR at reset time. The bank stays EUR-denominated as before
  (start_eur on the dashboard, accounting in USD via meme.EURUSD 1.1215). `bank_reset.sol_eur()` = median CoinGecko SOL/EUR + Kraken SOLEUR,
  sanity 10..1000 EUR; no sane quote -> RuntimeError before any state change (never guess). bank.json records `sol_eur_start`, `sol_source`, `bank_rule`.
  The 19:15 variant (bank in SOL units) and a flat 100 EUR were both superseded by the user at 19:23 and are not in the code.
- **History:** the bank was never 1 SOL before (epoch 1 = $100 on 20.10., epoch 2 = 100 EUR = $112.15 on 21.10. 20:21).
- **How (same as epoch 2):** open positions closed at the DexScreener mark (reason `reset: ...`, normal simulated exit; abort if a mark is missing),
  cooldowns created by those reset closes dropped, epoch-2 closed book -> archive/meme_epoch2_<tag>.json, history.csv -> archive/history_epoch2_<tag>.csv,
  bank.epochs += epoch 2 summary, risk day-open = new start (epoch_reset record), [BANK] line in meme.log. Shadow, learner seeds, journals untouched;
  the learner reads archive/meme_epoch*_*.json, so archive/ is now in the state manifest (mirrored to branch state).
- **Runner-safe:** run ONCE on the GitHub runner via gh/crontab.gh one-shot (`bank_reset.py --order "2026-10-23 19:23" --once`, flock),
  idempotent via bank.reset_order -> no race with the runner's 5-min state commits. Box never writes state.
- **Unchanged:** ticket 10 EUR ($11.21), MAX_OPEN 6 / TOTAL 8 / NP 3, stops, rules, Alpaca (separate paper book).
  Sizing caps the ticket at free cash (ticket = min(fixed, 2% liq, cash), skip < $1). At 93.26 EUR/SOL (= $104.59) cash covers ~9 full
  positions ($11.42 incl. refundable ATA rent), caps allow 8.
- **Dashboard:** "since reset (X € = 1 SOL, ...)", Hinweis "Start $… = X € = 1 SOL @ Y €/SOL, Epoche 3 seit …".
- **Tests:** tests/test_bank_reset_1sol_eur.py (6). `pytest tests --ignore=tests/backtest`: 119 passed.
- **Revert:** ~/.desk/backup_20261023_1920_bank_reset_1sol/ (bank_reset.py, dashboard files, manifest, crontab).

## 2026-10-24 01:24 + 01:25 — USER ORDER (Dominic): exit regime `2026-10-24_0124_tp30_60_fix20` + fast exits (meme main, new pairs, shadow)
- **Exit rules (meme.py `EXIT_TP_LADDER`, `EXIT_POST_TP_STOP`, `exit_decision`):** TP1 +30 % sells 1/3 of the INITIAL qty, TP2 +60 % another
  1/3, the last 1/3 runs. Gap through both in one check -> 2/3 at once, never sold twice. After any TP: FIXED stop at entry −20 %
  (no trailing). Before any TP the initial stop: PumpSwap −20 %, bonding curve −30 %, new pairs 0.30.
  REMOVED: profit lock (+15 % -> +5 %), trailing (+15 % arm / −25 %, trail_tight, trail_after_time_stop), TP +50 %/+100 % and the
  new-pairs STRONG ladder/trail (all tiers use the same ladder now). Constants TRAIL_*, LOCK_*, TAKE_PROFIT deleted.
- **Kept:** main 60-min time stop (closes even in profit), new pairs NORMAL 30 min / STRONG 180 min time stop only if not in profit,
  12 h max hold, volume decay (EXIT_RATIO, pools >= 2 h), new-pairs safety exits (dev sold, < 3 trades/10 min, RugCheck danger),
  10 € ticket, position caps, learner bounds.
- **Migration (`migrate_exit`, idempotent via `exit_regime`):** open real + shadow positions: TP hits derived from the fraction of the
  initial qty already sold (old 1/2 sold = TP1 done, TP2 sells 1/6; >= 2/3 sold = both done); peak already >= +30 % -> `tp_passed`
  -> fixed −20 % stop. Frozen plans keep their time stop / max hold. One `[REGIME] … migrated` log line per position.
- **Regime marker:** `logs/exit_regime.jsonl` (regime, since, all parameters, logged_at) + `[REGIME] exit regime … active` in meme.log;
  every new position / trade / shadow BUY-SELL-close record carries `exit_regime`; learner journal tags records (`legacy` before),
  reports `by_exit_regime` and never compares before/after across regimes in its auto-revert check.
- **Learner:** forbidden prefixes now also LOCK, TAKE_PROFIT, TP_, POST_TP, VC_, FAST_, NODATA, LIQ_PULL, RISK_, VOL_MIN_AGE,
  newpairs.VOL_COLLAPSE/SAFETY, shadow.* (EXIT_*, TRAIL, STOP_LOSS, TIME_STOP, MAIN_EXIT, newpairs.EXIT were already forbidden).
- **Why −50…−90 % despite the −20 % stop (01:25 order):** not the check frequency of the code path and not missing data. Checks already
  ran 5×/min (~12 s, each ≤ 1.1 s); only 4 NO PRICE events, all recovered. The deep losses are one-tick gap crashes between two
  checks: KIMCHI +18.8 % at 19:34:01 -> −98.1 % at 19:34:13; SpiderMan +58.8 % -> −60.1 % in 13 s; WOJAK NP −60 % at check 2/5.
  Epoch 1: 13 of 77 closes worse than −35 %; most stops filled at −31…−35 % (12 s slippage past −20 %). The sim fill uses the
  post-crash mark (+~0.5 % slippage), so it does not hide anything. Old volume decay was off for pools < 2 h (most trades).
- **Fast exits (01:25):** risk loop 5 -> 14 checks/min (every 4 s, last start 53 s, hard stop 57 s < cron timeout 58 s; still
  1 DexScreener batch + chain per check, pump.fun trades every 3rd check, GT fallback twice/min, NP safety every 3rd check) - stop
  evaluated on every poll. New exits: **volume collapse** m5 < 10 % of the trailing-hour 5-min average AND mark < entry +10 %,
  after >= 10 min hold, only if the hour had >= $5k volume (`EXIT_VC_*`); **liquidity pull** liquidity < 40 % of its peak while held
  (`EXIT_LIQ_PULL=0.60`); **no-data** no price for >= 90 s -> close, SIMULATED at last mark −10 % (`EXIT_NODATA_*`, flag
  `nodata_fill_assumed`, assumption). A single-candle rug can still fill far below −20 %; 4 s only shrinks the window 3×.
- **Calibration (in-sample, GT 1m bars, gross, ticket units = sum of per-trade returns):** 877 trades with candles (154 real = all
  real, 723 of 1457 shadow; GT fetch too slow for the rest). Baseline = new regime without VC. Chosen VC (0.10 / +10 % / 10 min /
  $5k): cuts 63 trades, blocked loss 4.99, gain lost 1.18, net +3.82 (real +1.29, shadow +2.52). 10 cut trades later touched 2× entry
  (data up to exit +4 h), but in none of them did the baseline keep a > +50 % result. Placeholder 0.25 / 0 % / 5 min / $1k was
  net −2.58 (36 later-2× cut) -> rejected. Sim limits: 1m bars, stops fill at the stop price (optimistic vs a 4-s poll), no fees.
- **Notable:** the kept main 60-min time stop fired 443× in the sim; 93 of those later touched 2× entry; without it +22.97 tickets
  in-sample (partly marks at end of data). Not changed (order: keep time exits) - flagged to Dominic.
- **Dashboard:** RISK / new-pairs texts, stop display (initial vs "Fix-Stop nach TP", no trailing), status "TP taken · runner" /
  "TP passed · fixed stop", reason labels for volume collapse / liquidity pull / no-data.
- **Tests:** tests/test_exit_regime.py (new: ladder, fixed stop, no trailing, migration, NP tiers, VC, liq pull, no-data, regime
  marker, learner, shadow), test_profit_lock_cooldown.py (lock tests -> removal tests), test_meme_stops.py (GT fallback check index).
- **Revert:** ~/.desk/backup_20261024_0125_exit_rebuild/ (meme.py, newpairs.py, shadow.py, learner.py, build_dashboard.py,
  dash_savip.py, CHANGELOG, KNOWLEDGE, test_profit_lock_cooldown.py); delete tests/test_exit_regime.py.
