# Trading Desk – nur Papierhandel (Paper Trading)

**Dies ist ein reiner Paper-Trading-Desk.** Es wird kein echtes Geld gehandelt:
- Alpaca-Sleeves (TREND, STOCKS, CRYPTO) laufen ausschließlich gegen den Alpaca-**Paper**-Endpoint
  (`paper=True` fest verdrahtet, `ALPACA_PAPER` muss `1` sein, sonst bricht der Code ab).
- Der Meme-Sleeve (pump.fun / PumpSwap) arbeitet mit **simulierten Fills** – keine Wallet, keine Keys, keine On-Chain-Orders.
- Die virtuelle Meme-Bank steht in `bank.json` (Epoche 2, 100 € Start).

Keine Anlageberatung, keine Gewinnversprechen.

## Aufbau
| Pfad | Inhalt |
|---|---|
| `*.py`, `*.sh` | Desk-Code (identisch mit `~/.desk` auf der Box) |
| `tests/` | Risiko-Regel-Tests (`pytest`, 66 Tests) |
| `gh/crontab.gh` | die Cron-Zeilen der Box, 1:1 vom GitHub-Runner ausgeführt |
| `gh/desk_loop.py` | Mini-Cron für den Runner (Berlin-Zeit, Übergabe, State-Commits, sauberes Ende) |
| `gh/state_sync.py` | State zwischen Desk-Ordner und Branch `state` kopieren / committen |
| `deploy/` | Allowlists für Code und State, Secret-Scan (`secret_scan.py`) |
| `box/` | Skripte für die Box: Code pushen, State holen, Cutover, Rollback, Secrets setzen |
| `.github/workflows/desk.yml` | 24/7-Job (~5 h 50 min pro Lauf, Neustart per Selbst-Dispatch + Zeitplan alle 6 h) |

Der **Zustand** (Positionen, Bank, Cooldowns, Dial, Logs …) liegt im separaten Branch **`state`**, damit die
Code-Historie auf `main` sauber bleibt. Der Job läuft nur, wenn `GH_LIVE` im Branch `state` existiert.

## Secrets
Alle Zugangsdaten kommen aus GitHub-Actions-Secrets (Umgebungsvariablen), auf der Box weiterhin aus den lokalen
Dateien. Im Repository liegen **keine** Schlüssel, Passwörter, Tokens oder E-Mail-Adressen. Details: `deploy/SECRETS.md`.

## Lokal testen
```bash
pip install -r requirements-dev.txt
python -m pytest tests --ignore=tests/backtest -q
```
