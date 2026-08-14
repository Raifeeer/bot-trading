"""Diagnóstico E3: qué hizo S78 durante el crash catastrófico."""
import pandas as pd

df = pd.read_csv("/home/ubuntu/backtests/bt_STRESS_E3_Catastrófico_-50%_3d_S78_trades.csv")
eq = pd.read_csv("/home/ubuntu/backtests/bt_STRESS_E3_Catastrófico_-50%_3d_equity.csv")
print("TRADES S78 E3:")
print(df.to_string())
print("\nEQUITY (muestra):")
print(eq.head(8).to_string())
print("...")
print(eq.tail(6).to_string())
print("\nEquity mínima:", eq["equity"].min(), "en",
      eq.loc[eq["equity"].idxmin(), "date"])
