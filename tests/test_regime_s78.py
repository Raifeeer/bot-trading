"""Prueba del detector de régimen S78 con datos reales de yfinance."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import pandas as pd
from data.feed import MarketDataFeed
from risk.regime import classify_regime, apply_crash_cooldown, put_choch_entry
from risk.floor import check_floor

feed = MarketDataFeed("alpaca")  # principal; cae a yfinance por ticker
UNI = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]

print("=== Probando régimen S78 con datos reales ===")
data = feed.history(UNI, "1d", days=400)
print(f"Tickers con datos 1d (210): {len(data)}")
for sym in UNI:
    df = data.get(sym)
    if df is None:
        print(f"  {sym}: sin datos")
        continue
    from risk.regime import _norm, _rsi, _sma
    d2 = _norm(df)
    close_now = float(d2["Close"].iloc[-1])
    rsi = _rsi(d2["Close"])
    s200 = _sma(d2["Close"], 200)
    bull = pd.notna(rsi.iloc[-1]) and rsi.iloc[-1] > 50 and \
        pd.notna(s200.iloc[-1]) and close_now > s200.iloc[-1]
    print(f"  {sym}: close {close_now:.2f}, RSI14 {rsi.iloc[-1]:.1f}, "
          f"SMA200 {("%.2f" % s200.iloc[-1]) if pd.notna(s200.iloc[-1]) else "NA"}, "
          f"bull={bull}, choch_bear={put_choch_entry(df)}")

print()
regime = classify_regime(data, UNI)
regime = apply_crash_cooldown(regime, {})
print("RÉGIMEN GLOBAL:", regime["regime"])
print("RESUMEN:", regime["summary"])

state = {}
fr = check_floor(99699.5, state)
print("\nPiso con equity 99,699.50 (bajo 99,900):", fr)
fr2 = check_floor(99950.0, state)
print("Piso con equity 99,950 (recuperado):", fr2)
