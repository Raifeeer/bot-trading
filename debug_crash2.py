"""Diagnóstico: ¿por qué S78 con crash_event queda en $100 en E2-E5?
Sospecha: con base_date=2026-05-15, los datos anteriores son reales (bull real)
— el detector no debería dejarlo en cash. Ver equity curves y trades."""
import pandas as pd
import glob

for f in sorted(glob.glob("/home/ubuntu/backtests/bt_stress_*.csv")):
    name = f.split("bt_stress_")[1].replace(".csv", "")
    df = pd.read_csv(f)
    if "trades" in name:
        print(f"== {name}: {len(df)} trades")
        if len(df):
            print(df[["symbol", "entry_date", "exit_date", "pnl_pct", "reason"]]
                  .head(12).to_string())
    else:
        eq = df
        print(f"== {name}: equity ini {eq['equity'].iloc[0]} fin {eq['equity'].iloc[-1]} "
              f"min {eq['equity'].min()} ({eq.loc[eq['equity'].idxmin(),'date']})")
