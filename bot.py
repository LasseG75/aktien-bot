"""Aktien-Bot: Moving-Average-Crossover für mehrere Aktien auf Alpaca (standardmäßig Paper-Trading).

Aufruf:
    python bot.py              -> normaler Lauf (prüft, ob der US-Markt offen ist, max. 1x pro Handelstag)
    python bot.py --test       -> sofortiger Testlauf: Signal berechnen, Konto lesen, NICHTS kaufen/verkaufen
    python bot.py --force      -> ignoriert Marktzeit und "heute schon gelaufen" (zum Ausprobieren)
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
from dotenv import load_dotenv

from strategy import BUY, SELL, compute_signal

BASE = Path(__file__).resolve().parent
LOG_DIR = BASE / "logs"
STATE_FILE = BASE / "state.json"
JOURNAL = LOG_DIR / "journal.csv"
ET = ZoneInfo("America/New_York")

log = logging.getLogger("aktien-bot")


def setup_logging() -> None:
    LOG_DIR.mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_DIR / "bot.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    log.setLevel(logging.INFO)
    log.addHandler(fh)
    log.addHandler(sh)


def load_config() -> dict:
    cfg = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
    for key in ("fast_ma", "slow_ma", "lookback_days"):
        if key not in cfg:
            raise KeyError(f"config.json: '{key}' fehlt")
    # Alte Form "symbol": "AAPL" weiter erlauben
    if "symbols" not in cfg:
        cfg["symbols"] = [cfg["symbol"]] if "symbol" in cfg else []
    cfg["symbols"] = [s.strip().upper() for s in cfg["symbols"] if s.strip()]
    if not cfg["symbols"]:
        raise KeyError("config.json: 'symbols' ist leer")
    if "trade_usd" not in cfg and "trade_qty" not in cfg:
        raise KeyError("config.json: 'trade_usd' oder 'trade_qty' fehlt")
    return cfg


def order_qty(cfg: dict, price: float) -> int:
    """Stückzahl pro Kauf: fester Dollarbetrag (trade_usd) oder feste Stückzahl (trade_qty)."""
    if cfg.get("trade_usd"):
        return max(1, int(float(cfg["trade_usd"]) // price))
    return int(cfg["trade_qty"])


def _fetch_alpaca(symbol: str) -> pd.Series:
    """Tagesschlusskurse über Alpaca (gleiche Keys wie fürs Handeln, läuft auch auf Servern)."""
    from datetime import timedelta

    from alpaca.data.enums import Adjustment, DataFeed
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("keine Alpaca-Keys")
    today = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    req = StockBarsRequest(symbol_or_symbols=symbol, timeframe=TimeFrame.Day,
                           start=today - timedelta(days=400), end=today,
                           adjustment=Adjustment.ALL, feed=DataFeed.SIP)
    df = StockHistoricalDataClient(key, secret).get_stock_bars(req).df
    if df.empty:
        raise RuntimeError("Alpaca lieferte keine Kurse")
    closes = df.xs(symbol, level="symbol")["close"]
    closes.index = closes.index.tz_convert(ET)
    return closes


def _fetch_yahoo(symbol: str) -> pd.Series:
    import yfinance as yf

    # Alpaca schreibt "BRK.B", Yahoo "BRK-B"
    hist = yf.Ticker(symbol.replace(".", "-")).history(period="1y", interval="1d", auto_adjust=True)
    if hist.empty:
        raise RuntimeError("Yahoo lieferte keine Kurse")
    return hist["Close"]


def fetch_closes(symbol: str, lookback_days: int) -> pd.Series:
    """Tagesschlusskurse – nur ABGESCHLOSSENE Handelstage. Erst Alpaca, bei Problemen Yahoo."""
    try:
        closes = _fetch_alpaca(symbol)
    except Exception as exc:
        log.warning("%s | Alpaca-Kurse nicht verfügbar (%s) -> Yahoo", symbol, exc)
        closes = _fetch_yahoo(symbol)
    # Läuft der Bot kurz nach Börsenstart, ist der heutige Tagesbalken erst Minuten alt -> weglassen.
    today_et = datetime.now(ET).date()
    closes = closes[[ts.date() < today_et for ts in closes.index]]
    return closes.tail(lookback_days)


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def write_journal(row: dict) -> None:
    new = not JOURNAL.exists()
    with JOURNAL.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()), delimiter=";")
        if new:
            w.writeheader()
        w.writerow(row)


def make_client():
    key = os.getenv("ALPACA_API_KEY", "").strip()
    secret = os.getenv("ALPACA_SECRET_KEY", "").strip()
    if not key or not secret or "hier" in key or "hier" in secret:
        return None, True
    paper = os.getenv("ALPACA_PAPER", "true").strip().lower() != "false"
    from alpaca.trading.client import TradingClient

    return TradingClient(key, secret, paper=paper), paper


def current_qty(client, symbol: str) -> float:
    try:
        return float(client.get_open_position(symbol).qty)
    except Exception:  # keine offene Position -> API wirft Fehler
        return 0.0


def has_open_order(client, symbol: str) -> bool:
    from alpaca.trading.enums import QueryOrderStatus
    from alpaca.trading.requests import GetOrdersRequest

    try:
        return bool(client.get_orders(GetOrdersRequest(status=QueryOrderStatus.OPEN, symbols=[symbol])))
    except Exception:
        return False


def place_order(client, symbol: str, qty: float, side: str):
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.trading.requests import MarketOrderRequest

    req = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY if side == BUY else OrderSide.SELL,
        time_in_force=TimeInForce.DAY,
    )
    return client.submit_order(req)


def process_symbol(client, cfg: dict, symbol: str, dry_run: bool, paper: bool) -> str:
    """Signal für eine Aktie berechnen und ggf. handeln. Gibt die Aktion zurück."""
    try:
        closes = fetch_closes(symbol, int(cfg["lookback_days"]))
        res = compute_signal(closes, int(cfg["fast_ma"]), int(cfg["slow_ma"]))
    except Exception as exc:
        log.error("%s | Datenabruf/Berechnung fehlgeschlagen: %s", symbol, exc)
        return "FEHLER"

    log.info(
        "%s | Schluss %s: %.2f | MA%d %.2f (vorher %.2f) | MA%d %.2f (vorher %.2f) | Signal: %s",
        symbol, res["date"], res["close"], cfg["fast_ma"], res["fast_ma"], res["prev_fast_ma"],
        cfg["slow_ma"], res["slow_ma"], res["prev_slow_ma"], res["signal"],
    )

    held = current_qty(client, symbol) if client is not None else 0.0
    if client is not None and has_open_order(client, symbol):
        log.info("%s | Es gibt schon eine offene Order -> nichts Neues.", symbol)
        return "OFFENE_ORDER"
    action, order_id, qty = "HOLD", "", 0.0
    if res["signal"] == BUY and held <= 0:
        action, qty = BUY, order_qty(cfg, res["close"])
    elif res["signal"] == SELL and held > 0:
        action, qty = SELL, held
    elif res["signal"] != "HOLD":
        log.info("%s | Signal %s, aber Position passt schon (%s Stk.) -> keine Order.",
                 symbol, res["signal"], held)

    if action != "HOLD":
        if dry_run:
            log.info("%s | [DRY-RUN] Würde jetzt %s %s Stk. ausführen.", symbol, action, qty)
            action = f"DRY_{action}"
        else:
            try:
                order = place_order(client, symbol, qty, action)
                order_id = str(order.id)
                log.info("%s | Order gesendet: %s %s Stk. | Order-ID %s", symbol, action, qty, order_id)
            except Exception as exc:
                log.error("%s | Order fehlgeschlagen: %s", symbol, exc)
                action = f"FEHLER_{action}"

    write_journal({
        "zeit_et": datetime.now(ET).strftime("%Y-%m-%d %H:%M"),
        "symbol": symbol, "kursdatum": res["date"], "schluss": res["close"],
        "fast_ma": res["fast_ma"], "slow_ma": res["slow_ma"], "signal": res["signal"],
        "aktion": action, "menge": qty, "bestand_vorher": held, "order_id": order_id,
        "modus": "dry" if dry_run else ("paper" if paper else "LIVE"),
    })
    return action


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--test", action="store_true", help="Nur prüfen, keine Orders")
    parser.add_argument("--force", action="store_true", help="Marktzeit/Tagessperre ignorieren")
    args = parser.parse_args()

    setup_logging()
    load_dotenv(BASE / ".env")
    cfg = load_config()
    dry_run = bool(cfg.get("dry_run", True)) or args.test

    client, paper = make_client()
    if client is None:
        log.warning("Keine Alpaca-Keys in .env gefunden -> reiner Simulationslauf ohne Konto.")
        dry_run = True
    elif not paper:
        log.warning("ACHTUNG: ALPACA_PAPER=false -> LIVE-KONTO mit echtem Geld!")

    today = datetime.now(ET).date().isoformat()
    state = read_state()

    if client is not None and not args.force and not args.test:
        clock = client.get_clock()
        if not clock.is_open:
            log.info("US-Markt geschlossen (nächste Öffnung %s) -> nichts zu tun.", clock.next_open)
            return 0
        if state.get("last_run_et") == today:
            log.info("Heute (%s ET) schon gelaufen -> übersprungen.", today)
            return 0

    if client is not None:
        acct = client.get_account()
        log.info("Konto: Cash %s $ | Depotwert %s $ | Kaufkraft %s $",
                 acct.cash, acct.portfolio_value, acct.buying_power)

    ergebnisse = {s: process_symbol(client, cfg, s, dry_run, paper) for s in cfg["symbols"]}
    log.info("Fertig: %s", ", ".join(f"{s}={a}" for s, a in ergebnisse.items()))

    if client is not None and not args.test:
        state["last_run_et"] = today
        write_state(state)
    return 1 if all(a == "FEHLER" for a in ergebnisse.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
