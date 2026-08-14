"""Diagnóstico rebote_rsi: ver señales reales en la ventana mar-jul 2026."""
import sys
sys.path.insert(0, '.')
import pandas as pd
import numpy as np
from data.feed import MarketDataFeed

feed = MarketDataFeed("yfinance")
syms = ["TSLA", "AMD", "PLTR", "TQQQ", "NVDA"]
hist = feed.history(syms, "1d", days=365)

def sma(s, n):
    return s.rolling(n).mean()

def rsi(s, n=14):
    from ta.momentum import RSIIndicator
    return RSIIndicator(s, n).rsi()

for sym, df in hist.items():
    sub = df[(df.index >= "2026-02-01") & (df.index <= "2026-08-14")]
    if sub.empty:
        continue
    r = rsi(sub["close"])
    hi60 = sub["close"].rolling(60).max()
    dip = sub["close"] <= hi60 * 0.85
    cross = r.ge(25) & r.shift(1).lt(25)
    sig = dip & cross & r.notna()
    print(f"{sym}: mínimo RSI={r.min():.0f} en {r.idxmin().date()}, "
          f"máx drawdown 60d={(sub['close']/hi60-1).min()*100:.1f}%, "
          f"señales dip+RSI25: {sig.sum()}")
    for d in sub.index[sig]:
        print(f"   señal {d.date()}: close={sub.loc[d,'close']:.1f}")
    # también revisar rebotes post-dip con RSI25-40 (entrada más permisiva)
    loose = (dip.shift(-3).any()) & r.between(20, 45) & r.shift(1).lt(25)
    print(f"   cruces RSI<25 (aunque no en dip): {(r.shift(1).lt(25) & r.ge(25) & r.notna()).sum()}")
    print()
