"""Contar señales rebote_rsi40 reales en jun-ago 2026 por ticker."""
import sys
sys.path.insert(0, '.')
import pandas as pd
from data.feed import MarketDataFeed
from loop_backtests import rebote_rsi40_entry

feed = MarketDataFeed("yfinance")
syms = ["TQQQ", "TSLA", "AMD", "PLTR", "NVDA", "SOFI"]
hist = feed.history(syms, "1d", days=365)
for sym, df in hist.items():
    dates = sorted(df.index.normalize())
    dates = [d for d in dates if pd.Timestamp("2026-06-01", tz="UTC") <= d <= pd.Timestamp("2026-08-14", tz="UTC")]
    count = 0
    for d in dates:
        sub = df[df.index.normalize() <= d]
        if rebote_rsi40_entry(sub, d) is not None:
            count += 1
            print(sym, d.date(), "SEÑAL")
    print(sym, "total:", count)
