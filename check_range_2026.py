"""Verifica cuántos datos recientes (2026) tiene cada ticker del reto vía feed."""
import sys
sys.path.insert(0, '.')
from data.feed import MarketDataFeed

feed = MarketDataFeed("yfinance")
syms = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
hist = feed.history(syms, "1d", days=365)
for sym, df in hist.items():
    recent = df[df.index >= "2026-04-01"]
    print(f"{sym}: total {len(df)} barras, {df.index.min().date()} -> {df.index.max().date()}, "
          f"desde abr-2026: {len(recent)}")
