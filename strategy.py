"""Moving-Average-Crossover-Logik – ohne Broker, damit sie separat testbar ist."""
from __future__ import annotations

import pandas as pd

BUY = "BUY"
SELL = "SELL"
HOLD = "HOLD"


def compute_signal(closes: pd.Series, fast: int, slow: int) -> dict:
    """Vergleicht die letzten zwei abgeschlossenen Tage.

    BUY  = schneller MA war gestern <= langsamer MA und ist heute > langsamer MA
    SELL = schneller MA war gestern >= langsamer MA und ist heute < langsamer MA
    sonst HOLD
    """
    if fast >= slow:
        raise ValueError("fast_ma muss kleiner als slow_ma sein")
    closes = closes.dropna()
    if len(closes) < slow + 1:
        raise ValueError(f"Zu wenig Daten: {len(closes)} Kurse, brauche mindestens {slow + 1}")

    fast_ma = closes.rolling(fast).mean()
    slow_ma = closes.rolling(slow).mean()

    prev_diff = fast_ma.iloc[-2] - slow_ma.iloc[-2]
    curr_diff = fast_ma.iloc[-1] - slow_ma.iloc[-1]

    if prev_diff <= 0 < curr_diff:
        signal = BUY
    elif prev_diff >= 0 > curr_diff:
        signal = SELL
    else:
        signal = HOLD

    return {
        "signal": signal,
        "date": str(closes.index[-1])[:10],
        "close": round(float(closes.iloc[-1]), 2),
        "fast_ma": round(float(fast_ma.iloc[-1]), 2),
        "slow_ma": round(float(slow_ma.iloc[-1]), 2),
        "prev_fast_ma": round(float(fast_ma.iloc[-2]), 2),
        "prev_slow_ma": round(float(slow_ma.iloc[-2]), 2),
    }


def recent_cross(closes: pd.Series, fast: int, slow: int, window: int = 3) -> dict:
    """Wie compute_signal, sucht aber die letzte Kreuzung innerhalb der letzten `window` Tage.

    Ergebnis enthält zusätzlich:
      cross      = BUY / SELL / HOLD (letzte Kreuzung im Fenster)
      cross_date = Datum des Tages, an dem die Kreuzung am Schlusskurs feststand
      tage_her   = 0 wenn die Kreuzung am letzten Schlusskurs war, 1 = einen Tag davor usw.
    """
    res = compute_signal(closes, fast, slow)
    closes = closes.dropna()
    diff = closes.rolling(fast).mean() - closes.rolling(slow).mean()
    res.update(cross=HOLD, cross_date=None, tage_her=None)
    for k in range(window):
        i = len(diff) - 1 - k
        if i < 1 or pd.isna(diff.iloc[i - 1]):
            break
        prev, curr = diff.iloc[i - 1], diff.iloc[i]
        if prev <= 0 < curr or prev >= 0 > curr:
            res.update(cross=BUY if curr > 0 else SELL, cross_date=str(closes.index[i])[:10], tage_her=k)
            break
    return res
