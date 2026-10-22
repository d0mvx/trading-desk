# Paper desk (~/.desk)  — PAPER ONLY, no wallets, no real funds

## Virtual desk bank ($100)
bank.json: start_capital=100, started 2026-10-20. desk_equity = 100 + P&L of OUR orders only:
  * Alpaca paper orders tagged client_order_id "desk-*" (replayed average-cost from fills; desk_bank.py)
  * meme sleeve SIMULATED fills (meme_positions.json)
The Alpaca account's $100k is never used for sizing. Alpaca min notional $1: smaller orders are skipped.
Sleeves: meme = this $100 bank (pump.fun, simulated). Since 2026-10-20 07:2x TREND/STOCKS/CRYPTO run on the Alpaca PAPER
account as a SEPARATE book (see "Alpaca PAPER sleeves" below); their orders are tagged alp-* and are ignored by desk_bank.py.
Runner changes vs author's script: budget from desk bank; desk-only holdings; exits sell desk qty (not
close_position, which would close the whole account position); min trade max($1, 5% of budget) instead of $25;
--dry-run; skips if desk orders are still open; refuses to run unless ALPACA_PAPER=1 (paper=True hard-wired).

## QUANT dial  (quant_dial.py, run_dial.sh) — daily 06:00 America/New_York
FRED keyless CSV (requests w/ curl UA; Python default UA gets throttled -> curl fallback), Alpaca free bars.
FRED fetch (2026-10-21): every fredgraph.csv response is validated (HTML maintenance/error page -> rejected, not parsed);
fallback chain per series: Cboe VIX_History.csv (VIXCLS), Fed H.4.1 DDP zip RESPPA_N.WW / RESPPLLDT_XAW_N.WW (WALCL / WTREGEN),
NY Fed ON RRP API (RRPONTSYD, USD->bn), FRED API if FRED_API_KEY, then last good cache dial_cache/<series>.csv. Same
age rules (from observation date) -> stale stays DEGRADED. BAMLH0A0HYM2 has no 2nd source (cache only). dial json: sources, fetch_notes.
Catch-up: dial_catchup.sh hourly at :20 (#DESK) re-runs run_dial.sh if newest dial > 20h, today's file missing after 06:30 NY,
or the newest dial has fetch errors; skips 05:50-06:30 NY; flock .dial.lock.
Net liquidity = WALCL/1000 - WTREGEN/1000 - RRPONTSYD (bn), aligned on WALCL Wednesdays (RRP value on/before).
Crypto daily bars: in-progress UTC day dropped. QQQ IEX: today's bar dropped before 16:00 NY.
Data age = now - observation date (00:00 UTC) / bar close. Max normal age: WALCL/WTREGEN 240h, daily FRED 120h,
crypto 48h, QQQ 120h. Older -> DEGRADED -> red. Dial floored to the 0.25 grid (never rounded up); raw also shown.
Crypto targets: close(t-30d)/close(t-365d)-1, top 2 positive, equal weight among selected; none -> cash.

## MEME sleeve (Solana only, pump.fun ecosystem) — scan.py, meme.py, meme_gate.py, run_meme.sh
Data: GeckoTerminal (keyless, <=9 calls/rolling 60s, cross-process limiter gt.py) dexes pump-fun (bonding
curve) + pumpswap (graduated) + new_pools; DexScreener fallback. Since 2026-10-20 14:58 also extra sources (sources.py):
pump.fun frontend-api-v3 (/coins/currently-live, /coins sort=last_trade_timestamp x2 pages, sort=market_cap complete=false)
+ DexScreener (token-profiles/latest, token-boosts/latest + top, search pumpswap/pumpfun, /tokens/v1 to resolve pairs).
Extra mints are deduped by mint (GT-listed mints skipped), loosely prefiltered (age 15m..72h, mcap, h1 buys >= 10, buys >= sells),
ranked by h1 buys, top 30 fetched via GT /pools/multi (1 call) and then run through the SAME scan.evaluate gates
(liquidity, age, curve-complete, stale data, wash cap, mcap, SOL quote) + Judge + RugCheck. Candidates per scan: 25 (was 10).
SCAN filters: quote SOL only; age 15m-72h; drop if sells>buys in m15 or h1; >=10 buys h1, >=2 buys m15 (lowered from 20/3 on 2026-10-20 01:03, user-approved);
bonding curve: mcap $15k-$90k, vol24 >= $20k, liq >= $5k, vol24/liq <= 100 (wash), real SOL < 80 (>= 80 = 'curve complete':
graduating/graduated, GT curve stats freeze); PumpSwap: mcap $40k-$8M, vol24 >= $40k, liq >= $12k, vol24/liq <= 40 (wash).
'stale data': reject only if txns m15+h1 and mcap are identical for 3 consecutive scans (current = previous 2;
per-pool streak in scan/fingerprints.json; changed 2026-10-20 ~02:00 from 2 scans, which hit active coins on GT cache repeats).
Rank (order only): log(buyers_h1/avg hourly buyers h6) - log(1+price_h1). Max 10.
(Changed 2026-10-20 ~01:55, user-approved; previous: PumpSwap mcap min $60k, wash 40x both venues, curve cutoff 90 SOL,
Judge score > 0 on top candidate only, ticket 6%, exits = volume decay only. Backup: backup_20261020_0148/.)
RUG PATTERN (USER ORDER 2026-10-21, rugpattern.py, pump.fun swap-api candles, 0 GT calls): after the Judge metrics, before RugCheck:
  rule 7 · first candle: skip if first 1m candle from launch >= +1000% AND >= 50% of rise to ATH (newpairs: >= +150%; no data -> skip;
  main: no data -> allow + log); rule 8 · bot-wash pattern on last 120 1s candles (micro-wash or sawtooth, see module docstring).
JUDGE: gates first (dial <24h old, meme dial >= 0.50, no degraded meme inputs, no daily-DD halt, < 3 open positions),
then candidates in rank order; the first that passes ALL of these is bought (max one new buy per run):
  unique buyers h1 >= 50; buys/sells m15 >= 1.2; unique buyers/buys h1 >= 0.25 (anti-bot); price change h1 +10%..+300%;
  coin not already held (1 position per mint); RugCheck hard gates (api.rugcheck.xyz/v1/tokens/<mint>/report, keyless,
  5 s timeout, cached per mint 10 min in rugcheck_cache.json): no mint authority, no freeze authority, transfer fee 0,
  rugged false, no 'danger' risks, PumpSwap pool LP locked >= 95%, creator <= 5% of supply, largest non-pool holder
  (excl. AMM/locker/curve accounts) <= 15%, insiders (graphInsidersDetected) <= 10. RugCheck unreachable -> no buy
  ('rugcheck unavailable'). RugCheck is only called for candidates that already pass the buyer/flow gates.
  Decisions + reasons per candidate are logged as type=judge in scan/rejects-YYYY-MM-DD.jsonl. meme.py dry = dry run.
SIZE: ticket = min(3% x meme bank x meme dial, 2% x pool liquidity, cash); skip if < $1 or fee >= 10% of ticket. Max 3 open.
FILLS (SIMULATED) at fresh live GT price. Fees (https://pump.fun/docs/fees, updated 17 Oct 2026):
bonding curve 1.25%; PumpSwap canonical SOL pools tiered 1.25% (<420 SOL mcap) down to 0.30% (>=98,240 SOL);
+ pump.fun app platform fee 0.45% (no referral; Terminal/3rd-party exempt; PUMP_APP_FEE env) + ~$0.002 network.
Slippage: constant-product impact notional/SOL-reserve + 0.5% latency. Bonding-curve SOL reserve =
sqrt(30 x 1.073e9 x price_SOL) (virtual reserves); PumpSwap reserve = liquidity/2.
RISK (every 1 min, cron `* * * * *` under flock -n .risk.lock). Prices for all open positions in ONE DexScreener
/tokens/v1 call (0 GeckoTerminal calls; GT multi fallback only if DexScreener fails, with a 15 s budget deadline).
A held bonding-curve coin that graduated is re-pointed to its most liquid PumpSwap pair. Exits at live price - slippage - fee:
stop-loss mark <= entry fill x 0.70 on bonding-curve entries / x 0.80 on PumpSwap entries (frozen at entry, since 2026-10-20 14:58);
trailing stop mark <= peak x 0.75 only once armed (peak >= entry fill x 1.15, so the trail is always above the hard stop);
24h COOLDOWN (meme_cooldown.json, mint + pool) after any stop-loss or any losing full close -> SCAN reject 'cooldown';
time stop 60 min after entry; take-profit: sell
half once at mark >= entry fill x 1.50; volume decay h6/(h24/4) < 0.20; daily 4% drawdown on desk equity (Berlin day open)
-> flat all + halt entries for the day. Stops are checked once a minute: fills can gap well past -20%.
Cadence (meme_gate.py, cron `* * * * *` under flock -n .gate.lock; changed 2026-10-20 01:30 on user request):
EVERY 1 MIN until 2026-10-21 01:30 Berlin (last 1-min scan 01:29), then hourly on :40 (2026-10-21 01:40 ..
2026-10-28 00:40), then stops and logs "schedule ended". The old 30-min phase was dropped (covered by the 1-min phase).
Per scan (since 2026-10-20 14:58): 6 GT list calls (pump-fun p1-2, pumpswap p1-2, new_pools p1-2) + 1 GT /pools/multi
(extra sources + watchlist refresh, top 30) + <= 1 GT OHLCV (dip check) = <= 8, all through the 9/rolling-60s limiter (calls that would
wait fail fast). Fill price: DexScreener first, GT fallback. pump.fun ~4 calls, DexScreener ~5-7 calls per scan (limits 60-300/min).
DIP ENTRY (Judge, after buyer/flow gates + RugCheck): buy only if price is 12..40% below its 60-min high (GT 1-min OHLCV
highs + prices implied by m5/m15/m30/h1 changes + watchlist observations; a real candle high is required) and m5 >= -10%.
Otherwise the coin goes on meme_watchlist.json (expires 60 min after added, max 40) and is re-fetched/re-checked every scan
with all gates (h1 price floor relaxed to >= 0% while watchlisted); 'dip too deep' or a RugCheck fail removes it. scan.py stops issuing GT calls after 40 s
(gt.get deadline: no long 429 back-off / limiter waits past it), so a run cannot run into the next minute.
Overlaps: flock -n on gate and risk; meme.py serializes pipeline vs risk; run_meme.sh shares .build.lock with the
cron dashboard build. Run durations: logs/meme_run.log ("run_meme ... done rc=0 N.Ns").
Reject detail file cap raised 5 MB -> 40 MB/day (1440 runs/day; dashboard reads only the last 4 MB).

## Cron (Debian cron 3.0 has no CRON_TZ)
NY-time jobs fire in a Berlin window and tz_gate.sh executes only when America/New_York time matches -> DST-safe.
Cron must be running: `sudo service cron start` (container has no systemd; restart after a box reboot).
Dashboard: build_dashboard.py -> dashboard/index.html (+ /workspace/desk-dashboard.html), every 1 min and after
each dial/meme run. Served by `python3 -m http.server 8080` from ~/.desk/dashboard.

## Bonding-curve liquidity (since 2026-10-20 00:57)
GeckoTerminal's reserve_in_usd is 0/null (or inconsistent) on many pump.fun curve pools. For SOL-paired bonding-curve
pools liquidity is DERIVED from the curve (no extra API calls): vSOL = sqrt(30 x 1.073e9 x price_SOL),
real_SOL = vSOL - 30, liquidity = real_SOL x SOL_USD (one-sided: the SOL sellers can actually withdraw).
The $5k filter and the 2%-of-liquidity ticket cap use this value; slippage uses the same curve state
(impact = notional / (vSOL x SOL_USD)). Dashboard shows these with '~'. Derived real SOL > 90 => 'curve data
mismatch' reject. Non-SOL (custom pair) curves keep the GeckoTerminal value and are rejected by 'quote not SOL'.
DexScreener /latest/dex/tokens/<mint> was not used (would add calls; the formula matched GT within 0.1% where GT had data, e.g. SPORE ~$8,939 vs GT $8,934).

## Live dashboard + access
build_dashboard.py writes dashboard/index.html (with embedded data fallback) + dashboard/data.json (no keys/token;
leak guards assert). Cron every 1 min (flock), plus after every meme scan/risk run and dial run. Reads only local
state + Alpaca paper (account/positions/orders); never calls GeckoTerminal. History snapshot at most every ~5 min.
Page polls ./data.json every 15 s, swaps sections in place (keeps <details> open state + scroll), live dot turns
gray when data > 3 min old; opened as a file it shows 'static' and uses the embedded data.
serve.py (stdlib) on 127.0.0.1:8080 serves only index.html/data.json/apple-touch-icon.png from dashboard/ and only
under /<token>/ or ?k=<token> (token in dash_token, 600); everything else 404; token never logged.
watchdog.sh (cron */5) restarts serve.py; cloudflared quick tunnel is DISABLED (tunnel_disabled flag) because this
box cannot reach Cloudflare's edge (UDP+TCP 7844 blocked, HTTP(S)-proxy-only egress). Remove the flag to retry;
quick-tunnel URLs change on every restart and are written to public_url.txt.

## here.now (private permanent dashboard)
herenow_publish.py (cron */2, +25 s after the build): Site [redacted], display name "Grok Bot Trading Desk",
no TTL, password mode (password in herenow_site.json, 600; key in ~/.herenow/credentials, 600). Uploads only
index.html, data.json, apple-touch-icon.png from a staging copy; manifest carries sha256 so unchanged files are
skipped; index.html refreshed at most every 30 min, data.json whenever it changed. Free-plan publish limit is
60/hour (paid 200/hour): main site 30/h + widget feed 12/h = 42/h. On 429 it waits Retry-After; on errors retries
next run. Visitors log in once (POST password -> cookie); the page's same-origin fetch of data.json sends the cookie
(credentials:'same-origin', cache:'no-store', ?_=timestamp buster; here.now serves max-age=3600 but updates are
visible immediately because each publish is a new version).
Widget feed: separate PUBLIC Site [redacted] with an empty index.html and widget.json at a random 32-hex path
(numbers only). /workspace/GrokDesk-Widget.js reads it. cloudflared stays disabled (tunnel_disabled).

## Alpaca PAPER sleeves (ON since 2026-10-20 07:2x Berlin, user request; backup: backup_20261020_0705/)
Sizing = Alpaca PAPER account equity (get_account().equity, $100,000 at switch-on). alp_common.py hard-wires paper=True and refuses
ALPACA_PAPER != 1; keys only from alpaca.env (file overrides shell env), never printed. Order ids: alp-trend-*, alp-stocks-*, alp-crypto-*.
* TREND (strategy.py, run_strategy.sh, TREND_SHARE=0.35): TQQQ if QQQ > SMA200 x1.01 (in) / stays while > x0.97 (out), else SHY.
  Owns the account's TQQQ/SHY positions; min trade $25 (author). 15:45 NY Mon-Fri.
* STOCKS (stocks.py): 0.50 x stocks_dial x equity, equal weight over max 16 names (cap 10% equity per name), 15:45 NY Mon-Fri.
  Priority: held names still listed -> names on both lists -> alternate DRIFT/INSIDERS. Rebalance only if >25% off target.
  Sell: name off BOTH lists; stocks_dial < 0.50 -> whole sleeve to cash. A null list = hold (its held names kept, no new buys).
  Dial missing/stale (>26h) -> hold, no orders. Never touches TQQQ/SHY or crypto.
* LISTS (run_alp.sh lists, 07:30 NY Mon-Fri; logs/lists.log):
  INSIDERS lists_insiders.py: SEC EDGAR daily form index -> every Form 4 full submission (6 req/s, UA from sec.env SEC_USER_AGENT),
    cached per filing day in lists/form4/. >=3 distinct reporting owners with code P (acquired) buys, trade date in last 30 days,
    total > $500k (joint filings split evenly), excl. aff10b5One / 10b5-1 footnotes; must be active+tradable on Alpaca.
    Any filing day not crawled -> status null (hold).
  DRIFT lists_drift.py: Nasdaq earnings calendar (api.nasdaq.com, unofficial, keyless) for the last 40 completed sessions; guards
    >=2 estimates, mcap >= $300M, price >= $5, tradable; top decile = p90 of % surprise over all eligible reports in the window;
    closed up on report day via Alpaca SIP daily bars: pre-market close(D)>close(D-1), after-hours close(D+1)>close(D), timing
    unknown (Nasdaq hides timing for past dates; timing is recorded from upcoming calendars in lists/earnings/_timing.json from
    now on) close(D+1)>close(D-1). Calendar hole -> null.
* CRYPTO (crypto.py): 0.15 x crypto_dial x equity into Quant crypto_targets (top-2 positive 12-1m momentum, equal weight), 20:05 NY daily.
  Sell when crypto_dial < 0.50 or coin out of targets. GTC notional orders.
* KILL SWITCH (killswitch.py, every 30 min): equity < last_equity x 0.96 -> close_all_positions(cancel_orders=True) = DELETE
  /v2/positions?cancel_orders=true on PAPER (whole account incl. TQQQ/SHY, as in the article); alp_kill.json = flat for the rest of
  the New York day (TREND/STOCKS/CRYPTO skip). --dry-run / --simulate-drop PCT for tests. State: kill_state.json.
Wrapper run_alp.sh stocks|crypto|kill|lists [--dry-run] (flock .alp.lock); logs: logs/alpaca_sleeves.log (dashboard activity), alpaca_run.log.

## Meme volume-decay rule (article) — pool-age aware (2026-10-20 07:17)
Article: avg_6h = volume.h24/4, ratio = volume.h6/avg_6h, ratio < 0.20 -> close fully. h24/4 is only a 6h average for pools >= 24h old;
a 3h-old pool has h24 == h6 -> ratio 4.0 (never fires). meme.vol_decay() uses the pool age (DexScreener pairCreatedAt / GT pool_created_at):
>= 24h exactly the article; 6-24h h6 / (h24 / (age/6)); 2-6h h1 / (h6 / age) (hour analog); < 2h or unknown age with h24==h6 -> off.
Ratio + mode are stored per position (vol_ratio, vol_mode) and logged.

## JEV (optional Judge tie-breaker) — jev.py, inactive without a key
Jev = TypeSafe AI's "System One" decision model (https://typesafe.ai, docs https://docs.typesafe.ai, POST https://api.typesafe.ai/v1/systemone,
Bearer key from https://console.typesafe.ai). Activate: copy jev.env.example -> jev.env (chmod 600) and set JEV_API_KEY (or env TYPESAFE_API_KEY).
Hard gates stay: Jev only chooses among up to JEV_MAX_CANDS=3 candidates that passed the rule Judge AND RugCheck (1 call/run, only if >=1 passed).
Buy only if choice != none, confidence >= 0.50 and noul(cont_N) >= 0.55. API error -> JEV_FAIL=rule (rule-based pick) or skip. Log: logs/jev.log.

## WALLET SIGNAL (2026-10-20 15:3x, user request) — scan/wallet_signal.py, cron every minute (flock .wallet.lock, timeout 30)
Vetting of 5 user-supplied wallets (public RPC getSignaturesForAddress/getTransaction, DexScreener; samples, not full history):
  215nhc... COPYABLE (whale, human pace <=9 trades/h, graduated PumpSwap coins ~10-60 min after graduation, 2-15 SOL buys,
            holds minutes-days; 8 closed in ~3.5 days: 2 wins, +151 SOL total but one +216 SOL winner, others -65 SOL)
  EwJYY4... COPYABLE-weak (5 tokens bought in 7d, mostly non-pump.fun/USDC-quoted, holds hours; 1 closed trade)
  29yFze... INSIDER-DEV (creates pump.fun coins, buys own coin in creation block, sells after ~4 s) -> excluded
  3VUNtV... SNIPER/fast scalper (buys pump.fun curve coins 13-60 s after creation, median hold 77 s) -> excluded
  FLyBjf... MEV/arb bot vault (never signs; ~600 txs/min by 5 bot signers via program DhpyNW..., stopped 07:09) -> excluded
Output scan/wallet_signal.json {mint: {wallets, first_buy_ts, sol, buys}} = BUYS of the COPYABLE wallets in the last 6 h
(state: scan/wallet_signal_state.json). Signal ignored if file older than 10 min. Use: sources.py adds these mints as
extra candidate source "wallet" (prioritized for GT enrichment, same loose prefilter); scan.py annotates c["wallet"] and
sorts watchlist first, then wallet count (2+ > 1 > 0), then score. ALL scan/Judge/RugCheck/dip/cooldown gates unchanged;
sells are never copied; paper only. Dashboard: 'Wallet: n of 2' under the token name; [FILLS] BUY line carries the tag.
Rollback: backup_20261020_1528_wallet/ (scan.py, sources.py, meme.py, build_dashboard.py, README.md, crontab.txt) + remove cron line.

## NEW PAIRS sleeve (newpairs.py) — 2026-10-20 16:0x, user request (backup: backup_20261020_1555_newpairs/)
PAPER, simulated fills, same $100 meme bank/positions file (meme_positions.json, sleeve="newpairs"). Own cron line every 1 min
(flock .newpairs.lock, timeout 55 s) until 2026-10-28 01:40 Berlin (self-stops) — stays 1-min after the meme gate goes hourly. 0 GT calls.
Data: pump.fun frontend-api-v3 /coins?sort=created_timestamp (3 pages = newest 150 launches ≈ 4-5 min; ~25-35 launches/min),
metadata stored in scan/newpairs_seen.json (75 min); /coins-v2/<mint> (SOL/USD ratio, security verdict, banned); bonding curve account
from public RPC getMultipleAccounts (reserves/progress/complete; virtual SOL differs per curve so progress = (793.1M - real tokens)/793.1M);
swap-api.pump.fun/v2/coins/<mint>/trades (incremental cache scan/newpairs_trades.json; buyers, sells, dev sells, first-2-slot snipers);
/coins?creator=<dev> (dev launch history, cache 30 min); RugCheck (shared cache with meme.py).
NARRATIVE (0-100): scan/narratives_static.json (famous_people, crypto_figures, classic, animals, ai, events; w 1-10) + optional
scan/narratives_trending.json (written by a separate hourly job; ignored if missing/unparseable/>3h old). Best match 7 x w (name/symbol; description x0.7),
+3 per extra term (max 9), +10 if a trending term matched; socials own X +10 / X post +6 / X community +6 / real website +6 / launchpad page +2 / TG +3,
no socials -20, no image -10; copycat (same ticker in 1h, not the leader = most real SOL then earliest) -30, crowded ticker leader (>=4) -5;
impersonation: X link is the celeb's own handle -25, 'official/real' claim about a person -15; spam wording -10; bot-deployer text -10.
PASS >= 70 (famous person in name + any real social; classic meme needs own X + website or trending; generic cat/dog/AI never alone). STRONG tier >= 85.
SAFETY (all required): age 2-15 min, SOL quote, curve not complete (feed + chain), pump.fun verdict allow, transfer fee 0, curve progress 5-60%,
>= 25 unique buyers (excl. dev), buys > sells, dev never sold, first-2-slot snipers/bundle <= 10% of supply (unknown -> reject),
dev not a serial launcher (<= 2 other coins in 24h, <= 9 in 7d, not a full 50-coin page), then RugCheck gates (meme.rugcheck_gates).
ENTRY: same dial/halt gates as Judge, cooldown, not held, max 2 new pairs and max 4 overall (main sleeve still max 3); ticket min(1.5% x meme bank x dial,
2% of real curve SOL, cash), min $1; fill at the on-chain curve price + curve slippage + 1.25% curve fee + 0.45% app fee. One buy per run (highest score).
EXITS (meme.py risk, per-position "exit" plan; main-sleeve positions unchanged): hard stop -30% always; safety exits every minute
(dev wallet sells, < 3 trades in 10 min after 10 min held, RugCheck rugged/mint/freeze/danger every 5 min); NORMAL (70-84): 1/2 at +50%,
trail -25% once +15%, time stop 30 min. STRONG (>=85): 1/3 at +100%, 1/3 at +300% (fractions of initial qty), rest trails -35% once +50%,
time stop 180 min only if not in profit, 12 h max hold; graduation re-points to the PumpSwap pair (no exit). Volume-decay rule applies once pool >= 2 h.
Prices in risk: DexScreener -> chain curve (newpairs.pf_price) -> GT fallback.
Logs: scan/newpairs-YYYY-MM-DD.jsonl (narrative decision once per coin/score change + every safety verdict + buys), scan/newpairs_latest.json (dashboard card),
logs/newpairs.log (per-minute summary); meme.log only gets BUY/SIZE and runs with a safety pass. Dashboard card "NEW PAIRS". `newpairs.py dry` = no positions written.

## 2026-10-20 19:48–20:10 Berlin — six approved upgrades (PAPER only; Alpaca files/cron untouched)
Backup: `backup_20261020_1948_upgrades/` (code, state jsons, crontab.txt, scan/*.py).
1. **Fast exits** — `meme.py risk` (cron every minute, `flock -n .risk.lock timeout -k 2 58`) runs 5 exit checks per minute
   (0/12/24/36/48 s; no check starts after 50 s; SIGALRM at 56 s). Prices: DexScreener `/tokens/v1` batch (30 mints/call,
   limit 300/min; we use ~5–30/min) + on-chain pump.fun curve read for curve coins DexScreener doesn't index. **0 GeckoTerminal
   calls** (the old GT fallback in RISK is gone). State: every read-modify-write of `meme_positions.json` (pipeline fill,
   newpairs fill, each exit) holds the short `.pos.lock` and reloads inside it; pipeline and risk no longer share `.meme.lock`.
   Daily 4% DD check once per minute (check 1). Status lines logged once per minute; exits logged immediately with `[check n/5]`.
2. **Meme scan stays 1-min** until 2026-10-28 01:40 Berlin (meme_gate.py: hourly phase removed). Same GT budget per run.
3. **Shadow book** — `shadow.py`, `shadow_positions.json`, `logs/shadow_trades.jsonl`, `logs/shadow.log`, lock `.shadow.lock`.
   Virtual trades (same `sim_buy`/`sim_sell` + same `exit_decision`, checked inside the fast loop) for: main max-open, main
   one-buy-per-run, main bonding-curve (item 4), main single failing gate (SCAN filter / JUDGE metric / RugCheck / dip; PumpSwap),
   new-pairs max-open / one-per-run / single failing safety gate. Dedupe (mint, category) 120 min; caps 10 open per category,
   150 total. Shadow checks never use OHLCV/GT; RugCheck from cache or ≤3 (main) / ≤2 (newpairs) new calls per run. Dashboard card
   "SHADOW TRADES" (win rate, realized P&L, avg %, open P&L per category); `shadow.py summary` prints the same.
   **Rejects**: compact (20 rejects/run, compact fields/JSON, ~15 kB/run ≈ 22 MB/day vs 40 MB cap); a day file ≥ 40 MB is rotated to
   `rejects-DATE.partN.jsonl.gz` and restarted, so per-coin details never stop (today's 45 MB file → part1.jsonl.gz).
4. **Main sleeve: no real buys on the bonding curve** (JUDGE marks them "shadow only"; curve coins are not watchlisted). NEW PAIRS unchanged.
5. **Costs**: + $0.04 priority fee per tx (buy and every sell) on top of $0.002 network + venue/app fees + slippage; token-account
   rent 0.00203928 SOL per buy as a refundable deposit (reduces free cash while open, refunded on the full exit = $0 net P&L).
6. **Profit protection** (main + new-pairs NORMAL): 50% of initial at +50%, another 25% of initial at +100%; trailing −25% → −20%
   once peak ≥ +100%. NEW PAIRS NORMAL: 30-min time stop only if not in profit, else trailing stop takes over (force-armed); 12 h cap.
   STRONG unchanged. Legacy main positions: qty_initial/tp_hits derived from tp_done.

## STOP ALL + Alpaca risk audit (2026-10-20 21:24 / 21:55, see CHANGELOG_research.md)
`touch ~/.desk/STOP_ALL` = no new BUYS anywhere (meme.book_add for main + new pairs; every Alpaca submit via alp_common.submit_block_reason);
exits, stops, kill switch keep running. `rm ~/.desk/STOP_ALL` resumes. Kill switch: journal logs/alp_kill.jsonl + alp_kill.json first, then
cancel_orders() + verify none open, then close all. kill_active() FAILS CLOSED on a corrupt alp_kill.json (no Alpaca orders until fixed/removed).
STOCKS: forced trim above 10% of equity; no top-up of a held name below its avg entry. Backtests/research: tests/backtest/ (STATUS.md, reports/).
