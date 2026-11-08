# desk2 Home: Offene PAPER-Trades

Approved by Dominic on 8 Nov 2026, 14:19 CET: "Ja, bau die Anzeige so ein."

## Goal

Show currently open PAPER trades on the existing desk2 Home screen, directly under the balance: coin, USD stake, unrealized PnL in USD and percent, entry, last price, stop, trail when one exists, and the pump.fun link. Refresh with the desk's existing poll and balance stream. An empty book, a missing price, a dead connection, and a cached snapshot each say what they are.

## Where it goes

Inline section on `#/home`, between the warning line and the chart. Same PWA, same styles (`.sect`, `.pos`, `.krow`, `.empty`, `.err`, `.up`, `.down`, `.btn.s`). No new page, modal, route, or dependency.

A separate page or sheet would hide the list behind another tap. The open book is one row per mint, so the Home section is the whole feature.

## Data

`GET /api/state` already returns `positions` from `account.open_positions()` (`closed_at IS NULL` and `mode` equal to `desk.mode`). The Home client never read that array. This change adds derived display fields and renders them.

Each open position gains:

| Field | Rule |
|---|---|
| `name` | existing `name_of` (symbol, else name, else short mint) |
| `link` | existing `links.coin_url(mint)` only |
| `last` | latest `prices.price` where `price IS NOT NULL`; otherwise JSON `null` |
| `last_at` | that row's `prices.ts`; otherwise `null`. Never the request time |
| `unrealized_usd` | fee-aware mark, or `null` |
| `unrealized_pct` | that USD figure divided by `size_usd`, times 100, or `null` |
| `stop_pct` | `risk.stop_pct_of` when entry and stop exist; otherwise `null` |
| `exit_line` | `risk.exit_line` only when `trail_active` and peak and stop exist; otherwise `null` |

Rows are ordered by `id` ascending. Closed rows and rows whose `mode` is not the desk mode stay out. With the desk in PAPER, a stored `LIVE` row is absent. `agents` Risk `guarding` remains the length of the same open set.

### PnL formula (checked against current code)

`account.unrealized` marks each open position as:

```text
size_usd * (last_price_or_entry / entry_price - 1) - (fees_usd or 0)
```

`fees_usd` on an open row is the entry-side cost. Exit costs are not guessed. `risk.close` stores realized `pnl_usd` only after the close, rounded to 4 decimal places. The coin route's `position.unrealized` is a different number: price change times size, no fee subtraction, and it substitutes entry when the last price is missing.

The Home figure matches the equity term when a last price and a non-zero entry and a size are present:

```text
unrealized_usd = round(size_usd * (last / entry_price - 1) - (fees_usd or 0), 4)
unrealized_pct = round(unrealized_usd / size_usd * 100, 4) if size_usd else null
```

Rounding to 4 decimals matches stored `pnl_usd`. The client then shows dollars with the existing `money()` (two fractional digits) and percent with the existing `pct()`.

Missing last price, entry of 0, or a null size: both unrealized fields are `null`. The client shows an em dash and "kein Kurs". It does not show 0 and it does not copy `account.unrealized`'s entry-price fallback. `equity()`, `free()`, and the executor stay on the current fallback so this display cannot change order size.

A stored last price of 0 or a negative last price is real data. It is shown and marked. It is not replaced with 0 PnL or with the entry price.

`pnl_usd` on an open row stays null. The section label is "Unrealisiert". Realized PnL stays in the balance and in closed activity, not in this list.

## Client

Title: **Offene PAPER-Trades**. Count in the section header.

- Fresh HTTP 200 with an empty list: "Keine offenen PAPER-Trades" and "Stand HH:MM" from `S.lastOk`, the client time of that 200.
- Fresh 200 with rows: one card each. Fields: coin, Einsatz (`size_usd`), Unrealisiert (USD and %), Einstieg, Kurs plus "Kurs HH:MM" from `last_at`, Stop, Trail or "Trail noch nicht aktiv", link "Auf pump.fun" (`target="_blank"` `rel="noopener"`) using `link` only.
- `last_at` more than 90 seconds before `server_time`: the Kurs time uses the existing orange. The PnL stays, because the price is real.
- `state.mode !== "PAPER"`: "Desk ist nicht im PAPER-Modus" and no figures.
- Names and URLs go through the existing `esc`.

`loadState` writes `S.lastOk` only after a real 200. A network failure that still has `CACHE["state"]` throws `Desk offline` with that body attached. The client keeps the previous rows, sets the snapshot stale, and does not move `S.lastOk`. The line reads "Stand HH:MM · Verbindung weg". The cached `last_at` and `server_time` stay the old values.

The first load, with no cache, shows the existing offline row and no invented trades. A later 200, including a genuine empty list, clears the stale flag and then updates `S.lastOk`.

The balance SSE event already updates equity about every 15 seconds and does not reload positions. It now also schedules the existing `refreshSoon()` → `loadState()`. The 30 second timer remains the fallback while online. Any failed GET retries `loadState` once; a successful state response is what clears offline. The old probe that called `setOnline()` without a new state body is removed, so a cached body cannot be stamped fresh.

`/index.html` is already `no-store`. The script URL gains `?v=20261108-open-trades` so a five-minute cached `/app.js` cannot outlive the new HTML. The service worker still caches nothing.

## Out of scope

No scanner, Jev, risk decisions, experiments, tags, settings, fees, or executor changes. No auth change. LIVE stays locked. No orders. `.github/workflows/desk.yml` stays disabled and untouched. No read or write of branches `state` or `state-desk2`. No new JS test framework.

## Production

Merging does not update the running Actions checkout. The next `desk2-paper` job checks out `main` at start, runs `pytest` in `desk2/desk/tests`, then serves the new files. Do not dispatch, restart, or cancel a run as part of this change.
