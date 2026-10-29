# Aktien-Bot (MA-Crossover, Alpaca Paper-Trading)

Nachbau des Bots aus Ray Fus Video „Complete Guide to building an AI Trading Bot with Claude for Beginners“.

**Strategie:** 20-Tage- und 50-Tage-Durchschnitt der Schlusskurse, für jede Aktie in `symbols` (config.json), letzte 100 Handelstage.
Pro Kauf ein fester Dollarbetrag (`trade_usd`, z. B. 1000 → bei 340 $ Kurs = 2 Stück). Verkauft wird die ganze Position.
Kreuzt der 20er den 50er nach oben → Kauf. Nach unten → Verkauf. Sonst nichts.
Funktioniert in Trendphasen, produziert in Seitwärtsphasen viele kleine Verlusttrades.

## Ordner

| Datei | Zweck |
|---|---|
| `config.json` | Aktienliste, MA-Längen, Betrag pro Kauf, `dry_run` |
| `analyse_kandidaten.py` | Vergleicht 20 große US-Aktien (Vola, Fehlsignale, Backtest 3 Jahre) |
| `.env` | Alpaca-Paper-Keys (aus `.env.example` kopieren) |
| `bot.py` | Der Bot |
| `strategy.py` | Nur die Crossover-Logik |
| `test_strategy.py` | Offline-Test der Logik |
| `setup_windows.bat` | Einmalig: .venv + Pakete |
| `run_bot.bat` | Startet den Bot (für die Aufgabenplanung) |
| `aufgabe_einrichten.ps1` | Legt die Windows-Aufgabe Mo–Fr an |
| `claude_desktop_config_ALPACA.json` | Block für Claude Desktop → Developer → Edit Config |
| `logs/bot.log`, `logs/journal.csv` | Protokoll jedes Laufs |

## Befehle (PowerShell)

```
cd "C:\Users\Lasse\Documents\aktien-bot"
.venv\Scripts\activate
python test_strategy.py        # Logik-Test
python bot.py --test           # Signal + Konto prüfen, keine Order
python bot.py --force          # Lauf außerhalb der Marktzeit (respektiert dry_run)
```

Echte (Paper-)Orders erst, wenn in `config.json` `"dry_run": false` steht.
`ALPACA_PAPER=true` in `.env` lassen, solange du nicht bewusst mit echtem Geld handeln willst.

Kein Finanzrat – ein Test-Setup mit Spielgeld.

## Server-Betrieb (GitHub Actions, kostenlos)

Der Bot läuft auf GitHubs Servern, der PC kann aus sein. Zeitplan steht in `.github/workflows/bot.yml`.
Keys liegen als **Secrets** im Repo (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`), nie als Datei.
Nach jedem Lauf schreibt der Workflow `logs/` und `state.json` zurück ins Repo.
Kurse kommen von Alpaca (Fallback Yahoo). Das lokale Dashboard rechnet die Signale live und zeigt Konto, Positionen und Orders direkt von Alpaca.
