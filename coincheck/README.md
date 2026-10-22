# coincheck – Solana-Memecoin-Analyse (CLI)

```
python3 ~/.desk/coincheck/coincheck.py <Mint | Pool | Link> [--text] [--no-gt]
```
* Standard: JSON-Report auf stdout. `--text`: kurze deutsche Zusammenfassung (für iPhone/Chat).
* `--no-gt`: gar keine GeckoTerminal-Calls (0 von 9/min Budget).
* Exit-Codes: 0 ok, 2 Eingabe-/Adressfehler (JSON `{"ok":false,"error":..,"message_de":..}`), 3 API down.
* Ohne venv gestartet, wechselt das Skript automatisch auf `~/.desk/venv/bin/python` (requests).

## Akzeptierte Eingaben
* Mint-Adresse (Base58, 32–44 Zeichen) oder Pool-/Pair-Adresse (PumpSwap/Raydium/Meteora/Curve) → Pool wird über DexScreener auf den Mint aufgelöst.
* Links: `dexscreener.com/solana/<pair|mint>` (auch kleingeschrieben), `pump.fun/coin/<mint>`, `gmgn.ai/sol/token/<mint>` (auch mit `xyz_`-Referral-Präfix),
  `fomo.family/token/<mint>` und beliebige andere URLs: jede Base58-Adresse (32–44 Zeichen) in Pfad, Query oder Fragment wird erkannt
  (Trennung an `/ ? & = _ -` usw.; SOL/USDC/Programm-IDs werden ignoriert; mehrere Kandidaten werden der Reihe nach bei DexScreener geprüft).
* **FOMO-Share-Links ohne Adresse**: der Link wird geladen (Redirects folgen), finale URL + `og:`/`twitter:`-Meta-Tags + HTML werden nach einer Adresse durchsucht.
  Findet sich nichts (oder nichts Handelbares): `Keine Adresse im Link gefunden – bitte die Coin-Adresse aus der FOMO-App kopieren.`
* Nicht Solana: `0x…`-Adressen, `dexscreener.com/ethereum/…`, `gmgn.ai/eth|bsc|base/…`, Tokens die DexScreener nur auf anderen Chains kennt → klare Fehlermeldung.

## Datenquellen (keyless, nur echte Daten)
| Quelle | wofür | Calls |
|---|---|---|
| DexScreener `latest/dex/tokens`, `latest/dex/pairs` | Pools, Preis, MC/FDV, Liquidität, Txns, Volumen, Preisänderung, Socials | 1–2 |
| RugCheck `v1/tokens/<mint>/report` | Authorities, LP-Lock je Markt, Top-Holder, Creator, Insider, Risks, Score | 1 |
| Solana RPC (public) | Mint-Account (Mint/Freeze-Authority, Token-2022-Transfer-Fee/Extensions), pump.fun Bonding-Curve-Account (Fortschritt) | 1–2 |
| pump.fun `swap-api.pump.fun/v2/coins/<mint>/candles` | OHLCV für pump.fun-Coins (Curve + PumpSwap) | 1 |
| Desk-Scan `~/.desk/scan/*.json` + `rejects-*.jsonl` | Unique Buyers aus dem letzten GT-Scan des Desks (nur wenn < 5 min alt) | 0 |
| GeckoTerminal über `~/.desk/gt.py` | max. **1** Call: OHLCV für Nicht-pump.fun-Coins, sonst Pool-Stats für Unique Buyers | 0–1 |
| Token-Metadaten-URI (IPFS) | Socials, falls DexScreener keine hat | 0–1 |

**GeckoTerminal-Budget**: Der Live-Desk verbraucht 8 von 9 Calls/60 s. coincheck nutzt denselben Lock/Zähler (`~/.desk/.gt_calls`),
macht nur dann einen Call, wenn *jetzt* ein Slot frei ist, mit 6-s-Deadline (wartet nie auf den Desk), und cached Antworten 3 min
(`.cache.json`). Ist der Slot belegt, fehlen eben OHLCV (Nicht-pump-Coins) bzw. Unique Buyers – das steht im Report (`warnings`) und
der Score wird entsprechend gedeckelt. Folge: zwei coincheck-Läufe innerhalb einer Minute → der zweite bekommt i. d. R. keinen GT-Call.
Der eine Call kann im ungünstigsten Fall den 9. Slot belegen, den der Desk für einen Fill-Preis nutzt; dessen Fill hat aber eine DexScreener-Fallback-Route.

## Report (JSON)
* `basics`: Name, Symbol, Mint, Haupt-Pool + Venue (pump.fun Bonding Curve / PumpSwap / Raydium / Meteora / Meteora DBC …), weitere Pools,
  Alter, Preis, MC, FDV, Liquidität (Curve: 2× reale SOL im Curve, geschätzt), Preisänderung 5m/1h/6h/24h, Volumen, Buys/Sells,
  Unique Buyers (falls verfügbar, mit Quelle/Zeit), Bonding-Curve-Fortschritt (RPC, geschätzt).
* `safety`: Mint-/Freeze-Authority, Transfer-Fee, Token-Programm, LP gelockt/verbrannt % (Haupt-Pool), Top-Holder & Top10 % **ohne** Pool/AMM/Locker/Curve-Konten,
  Creator/Dev %, Insider, Bundle-Hinweise (nur soweit RugCheck sie meldet), RugCheck-Risks + Score (0–100, niedrig = gut), Socials, `danger`, `warnings`.
* `momentum` (geschätzt): OHLCV-Quelle/Intervall, Trend (höhere Tiefs?), ATH-MC seit Candle-Beginn + Drawdown, Supports (MC-Level mit Bounce), Volumen-Trend.
* `verdict` (geschätzt): `kauf_score_pct`, Komponenten + Begründungen, angewandte Caps, Grund, Plan (Einstieg/Stop/Ziel als MC **und** Preis), „Was würde den Score erhöhen“.

## Kauf-Score (Regeln stehen als `CONFIG` oben im Skript)
Komponenten (Summe 100): **Sicherheit 30** · **Liquidität 15** · **Momentum 20** · **Orderflow 20** · **Einstieg 15**
* Sicherheit: 30 minus RugCheck-Warnungen (−4 je, max −12), Top10 > 30 % (−6) / > 20 % (−3), Creator > 3 % (−4), keine Socials (−4), LP-Lock < 99 % (−4), Metadaten änderbar (−2). Danger → 0.
* Liquidität: Liq/MC ≥ 0,15 → 15, ≥ 0,08 → 10, ≥ 0,04 → 6, sonst 2; Liq < 10k $ −5; Bonding Curve pauschal 10.
* Momentum: 1h +5…+100 % → 8 (0…5 % → 5, −15…0 % → 3, > 100 % → 4), 6h positiv +2, Volumen nicht fallend +2, höhere Tiefs +8 (seitwärts +4).
* Orderflow: Buys/Sells 1h ≥ 1,3 → 8, ≥ 1,1 → 6, ≥ 0,95 → 3 (> 2,5 = verdächtig → 4); 5m ≥ 1,1 +4; Unique Buyer/Buy ≥ 0,35 → 8, ≥ 0,25 → 5, ≥ 0,20 → 2 (unbekannt: 4 neutral).
* Einstieg: ≤ 10 % über Support → 15, ≤ 25 % → 9, weiter → 4, kein Support → 5; am ATH nach > 50 % 1h-Pump → 3; > 80 % unter ATH → 2.

**Harte Caps** (das Minimum gilt):
* **Danger → max 15 %**: Mint- oder Freeze-Authority aktiv, Transfer-Fee > 0, RugCheck „rugged“ oder irgendein RugCheck-Risk „danger“,
  LP < 90 % gelockt (AMM-Haupt-Pool), größter Nicht-Pool-Holder > 20 %, Creator > 10 %, Insider > 20, AMM-Liquidität < 3k $ (0 = LP gezogen).
* RugCheck nicht erreichbar → 35 · jünger als 15 min → 40 · Wash/Bot-Verdacht (Vol24/Liq > 40× oder Unique Buyer/Buy < 0,20) → 30 ·
  Abwärtstrend → 50 · am ATH nach Pump → 50 · 1h > +150 % → 50 · Unique Buyers unbekannt → 60 · keine Marktdaten → 0.

**Plan**: ≥ 65 % **und** Kurs ≤ 25 % über einem Support → „Kauf möglich (kleine Position)“; ≥ 65 % aber weit über Support → „Score hoch, aber nicht hinterherkaufen“ (Dip-Plan);
45–64 % „nur bei Dip/Bestätigung“, < 45 % „kein Kauf jetzt“, Danger → „kein Kauf – Sicherheitsrisiko“.
Einstieg = nächster Support unter dem Kurs (Swing-Tief ±3 Candles mit ≥ 8 % Bounce, Cluster 6 %); ohne Support −20 % vom MC (als Schätzung markiert).
Stop = Support −12 % (bzw. knapp unter dem nächsttieferen Support, wenn der näher liegt). Ziel = 95 % des ATH-MC, sonst +50 %.
MC ↔ Preis über MC/Preis-Verhältnis von DexScreener.

## Grenzen
* ATH/Supports nur so weit, wie die Candles zurückreichen (pump.fun: 1000 Candles; GT: 1000 Candles des Haupt-Pools; Intervall nach Alter 1m/5m/15m/1h/4h).
  Für Nicht-pump-Coins fehlt die Curve-Historie vor der Migration. Einzel-Trade-Wicks (> 2,5× Open/Close) werden für das ATH ignoriert.
* Unique Buyers gibt es keyless nur über GeckoTerminal (Desk-Scan oder 1 GT-Call) – sonst Score-Cap 60.
* Bundles/Sniper: keine keyless Quelle; nur was RugCheck als Risk meldet. Insider = RugCheck `graphInsidersDetected`.
* DexScreener-Daten können bei toten/gerugten Pools veraltet sein (z. B. Volumen trotz Liquidität 0).
* Public Solana RPC ist rate-limitiert; fällt er aus, kommen Authorities aus RugCheck.
* Keine Anlageberatung; alles mit `_est`/„geschätzt“ ist berechnet.

## Tests/Entwicklung
`COINCHECK_DS_URL` / `COINCHECK_RC_URL` überschreiben die API-Basis (nur für Ausfall-Tests).
