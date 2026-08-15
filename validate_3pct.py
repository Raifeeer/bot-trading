"""Valida que crash_event=0.03 no genere falsos positivos en datos reales
(ventana abr-ago 2026, misma de S78): comparar S78 base vs S78 con detector."""
import os
import sys

import pandas as pd

TOP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOP)

from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import run_scenario, UNI_RETO, SCENARIOS  # noqa: E402

feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
base = feed.history(UNI_RETO, "1d", days=365)

rows = []
for key, cfg in (("S78 base", dict(SCENARIOS["S78"])),
                 ("S78 crash3", dict(SCENARIOS["S78"], crash_event=0.03)),
                 ("S78 crash3-fr50", dict(SCENARIOS["S78"], crash_event=0.03,
                                          crash_frac=0.5))):
    _, tdf, ec, _, _ = run_scenario(key, cfg, base)
    eq = pd.DataFrame(ec)
    rows.append(dict(scenario=key, equity_final=eq["equity"].iloc[-1],
                     dd=(eq["equity"].min() / eq["equity"].max() - 1) * 100,
                     bear_cash=int((tdf["reason"] == "bear_cash").sum())
                     if len(tdf) else 0,
                     trades=len(tdf)))
out = pd.DataFrame(rows)
print(out.to_string())
out.to_csv("/home/ubuntu/backtests/bt_stress_validate.csv", index=False)
