# Branch `state` (Paper-Trading-Desk)

Laufzeit-Zustand des Paper-Trading-Desks (nur Papierhandel, keine echten Orders mit echtem Geld).
Wird vom GitHub-Actions-Job alle 5 Minuten aktualisiert; der Code liegt auf `main`.
Welche Dateien hier landen, steht in `deploy/state_manifest.txt` auf `main`. Jeder Commit läuft durch `deploy/secret_scan.py`.
