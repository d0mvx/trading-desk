# GitHub Actions secrets expected by `.github/workflows/desk.yml`

Names only. Values are copied by `box/set_secrets.sh` (piped, never printed). Never commit any of the source files.

| Secret | Required | Source on the box | Used by |
|---|---|---|---|
| `ALPACA_KEY` | yes | `~/.desk/alpaca.env` → `ALPACA_KEY` | alp_common, strategy, quant_dial, build_dashboard, meme (desk equity) |
| `ALPACA_SECRET` | yes | `~/.desk/alpaca.env` → `ALPACA_SECRET` | same |
| `SEC_USER_AGENT` | yes | `~/.desk/sec.env` → `SEC_USER_AGENT` (contains the SEC contact e-mail) | lists_insiders (SEC EDGAR), dashboard privacy guard |
| `HERENOW_API_KEY` | yes (publish) | `~/.herenow/credentials` → `HERENOW_API_KEY` | herenow_publish |
| `HERENOW_SITE_SLUG` | yes (publish) | `~/.desk/herenow_site.json` → `slug` | herenow_publish (existing password site; runner never creates a new one) |
| `HERENOW_SITE_PASSWORD` | yes (publish) | `~/.desk/herenow_site.json` → `password` | herenow_publish (re-applied + verified once per run), privacy guard |
| `HERENOW_WIDGET_SLUG` | yes (widget) | `~/.desk/herenow_site.json` → `widget_slug` | widget feed publish, privacy guard |
| `HERENOW_WIDGET_PATH` | yes (widget) | `~/.desk/herenow_site.json` → `widget_path` | widget feed publish, privacy guard |
| `DASH_TOKEN` | optional | `~/.desk/dash_token` | build_dashboard token-leak guard only (no server on the runner) |
| `FRED_API_KEY` | optional | not present on the box today (quant_dial falls back to the keyless FRED CSV) | quant_dial |

Not needed on GitHub: `GITHUB_TOKEN` for the job (Actions provides `github.token`), `JEV_API_KEY` (Jev is off: no `jev.env`).
`ALPACA_PAPER=1` is set in the workflow itself (not a secret).
