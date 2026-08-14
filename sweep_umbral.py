"""Barrido del umbral del detector crash_event para elegir el mejor
compromiso entre reactividad y falsos positivos."""
import os
import sys

import pandas as pd

TOP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOP)

from data.feed import MarketDataFeed  # noqa: E402
from stress_test import inject_crash  # noqa: E402
from loop_backtests import run_scenario, UNI_RETO, SCENARIOS  # noqa: E402

feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
base = feed.history(UNI_RETO, "1d", days=365)
base_date = pd.Timestamp("2026-05-15", tz="UTC")

scenarios = (
    ("E1 Flash -20% 1d", dict(crash_days=1, crash_mag=0.20), None),
    ("E2 Severo -35% 5d +rebote", dict(crash_days=5, crash_mag=0.35),
     dict(opct=0.5, n_days=70)),
    ("E4 Realista -30% 20d +débil", dict(crash_days=20, crash_mag=0.30),
     dict(opct=0.2, n_days=50)),
)

sc0 = dict(SCENARIOS["S78"])
hold0 = dict(SCENARIOS["S74"], tickers=UNI_RETO)

rows = []
for th in (0.03, 0.05, 0.08, 0.12, 0.15):
    for name, crash, rec in scenarios:
        data = inject_crash(base, **crash, base_date=base_date, recovery=rec)
        end = data[UNI_RETO[0]].index[-1].normalize()
        s78 = dict(sc0, crash_event=th,
                   window_dates=(str(base_date.date()), str(end.date())))
        _, _, ec, _, _ = run_scenario(f"sweep", s78, data)
        eq = pd.DataFrame(ec)
        rows.append(dict(umbral=th, esc=name, equity_final=eq["equity"].iloc[-1],
                         dd=eq["equity"].min() / eq["equity"].max() - 1))
        hold = dict(hold0, window_dates=(str(base_date.date()), str(end.date())))
        _, _, ech, _, _ = run_scenario(f"sweep_h", hold, data)
        eqh = pd.DataFrame(ech)
        rows.append(dict(umbral=th, esc=name, equity_final=eqh["equity"].iloc[-1],
                         dd=eqh["equity"].min() / eqh["equity"].max() - 1,
                         motor="hold"))
print(pd.DataFrame(rows).to_string())
pd.DataFrame(rows).to_csv("/home/ubuntu/backtests/bt_stress_sweep.csv",
                          index=False)
