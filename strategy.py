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
