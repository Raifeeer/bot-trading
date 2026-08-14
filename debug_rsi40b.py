"""Trace diario de señales rebote_rsi40 + spreads en tickers baratos, jun-ago 2026."""
import sys
sys.path.insert(0, '.')
import pandas as pd
from data.feed import MarketDataFeed
from loop_backtests import (rebote_rsi40_entry, build_spread, realized_vol,
                            UNI_RETO)

feed = MarketDataFeed("yfinance")
syms = ["SOFI", "F", "NOK", "BB"]
data = feed.history(syms, "1d", days=365)
start = pd.Timestamp("2026-06-01", tz="UTC")
end = pd.Timestamp("2026-08-14", tz="UTC")

for i, d in enumerate(sorted({ts.normalize() for df in data.values() for ts in df.index})):
    if not (start <= d <= end):
        continue
    for sym, df in sorted(data.items()):
        sub = df[df.index.normalize() <= d]
        if len(sub) < 80:
            continue
        e = rebote_rsi40_entry(sub, d)
        if e is None:
            continue
        rv = realized_vol(sub)
        spot = sub["close"].iloc[-1]
        for sc in (dict(delta_l=0.30, delta_s=0.10, risk_pct=0.15, max_rv=None),
                   dict(delta_l=0.25, delta_s=0.08, risk_pct=0.15, max_rv=None),
                   dict(delta_l=0.25, delta_s=0.08, risk_pct=0.30, max_rv=None)):
            sp = build_spread(spot, rv or 0.3, d, sc, side="call")
            net = sp["net"] if sp else None
            if net and net <= 100 * sc["risk_pct"] * 1.5:
                print(f"{d.date()} {sym}: spot={spot:.2f} rv={rv:.2f} "
                      f"d={sc['delta_l']}/{sc['delta_s']} net=${net:.2f} "
                      f"budget15=${100*sc['risk_pct']:.0f} entra={net <= 100*sc['risk_pct']}")
