"""Diagnóstico manual del detector de régimen S78 con datos reales.

NO es un test unitario: hace descargas de red en vivo. Todo el trabajo vive
dentro de `main()` detrás de un guard `__main__` a propósito — al estar en
`tests/` con nombre `test_*.py`, `unittest discover` lo importa, y si el
código de red corriera a nivel de módulo la suite entera se colgaría
esperando al feed (ocurrió el 17 ago 2026).

Uso manual:  python3 tests/test_regime_s78.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def main():
    os.chdir(os.path.join(os.path.dirname(__file__), ".."))

    import pandas as pd
    from data.feed import MarketDataFeed
    from risk.regime import (classify_regime, apply_crash_cooldown,
                             put_choch_entry, _norm, _rsi, _sma)
    from risk.floor import check_floor

    feed = MarketDataFeed("alpaca")  # principal; cae a yfinance por ticker
    uni = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]

    print("=== Probando régimen S78 con datos reales ===")
    data = feed.history(uni, "1d", days=400)
    print(f"Tickers con datos 1d: {len(data)}")
    for sym in uni:
        df = data.get(sym)
        if df is None:
            print(f"  {sym}: sin datos")
            continue
        d2 = _norm(df)
        close_now = float(d2["Close"].iloc[-1])
        rsi = _rsi(d2["Close"])
        s200 = _sma(d2["Close"], 200)
        bull = (pd.notna(rsi.iloc[-1]) and rsi.iloc[-1] > 50
                and pd.notna(s200.iloc[-1]) and close_now > s200.iloc[-1])
        s200_txt = ("%.2f" % s200.iloc[-1]) if pd.notna(s200.iloc[-1]) else "NA"
        print(f"  {sym}: close {close_now:.2f}, RSI14 {rsi.iloc[-1]:.1f}, "
              f"SMA200 {s200_txt}, "
              f"bull={bull}, choch_bear={put_choch_entry(df)}")

    print()
    regime = classify_regime(data, uni)
    regime = apply_crash_cooldown(regime, {})
    print("RÉGIMEN GLOBAL:", regime["regime"])
    print("RESUMEN:", regime["summary"])

    state = {}
    print("\nPiso con equity 99,699.50 (bajo 99,900):",
          check_floor(99699.5, state))
    print("Piso con equity 99,950 (recuperado):",
          check_floor(99950.0, state))


if __name__ == "__main__":
    main()
