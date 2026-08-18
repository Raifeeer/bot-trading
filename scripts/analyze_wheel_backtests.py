"""Analiza resultados Wheel sin seleccionar por una sola ventana."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RESULTS = Path("/home/ubuntu/backtests/wheel_backtests_2026-08-18_results.csv")
PREFIX = Path("/home/ubuntu/backtests/wheel_backtests_2026-08-18")


def main() -> None:
    df = pd.read_csv(RESULTS)
    df["profitable"] = df["return_pct"] > 0
    df["beats_buy_hold"] = df["return_pct"] > df["buy_hold_return_pct"]
    df["return_to_dd"] = df["return_pct"] / df["max_drawdown_pct"].abs().replace(0, pd.NA)
    df.to_csv(f"{PREFIX}_analyzed.csv", index=False)
    summary = df.groupby("scenario", as_index=False).agg(
        windows=("window", "count"),
        mean_return_pct=("return_pct", "mean"),
        median_return_pct=("return_pct", "median"),
        worst_return_pct=("return_pct", "min"),
        best_return_pct=("return_pct", "max"),
        mean_drawdown_pct=("max_drawdown_pct", "mean"),
        worst_drawdown_pct=("max_drawdown_pct", "min"),
        profitable_windows=("profitable", "sum"),
        beats_buy_hold_windows=("beats_buy_hold", "sum"),
        total_assigned_puts=("assigned_puts", "sum"),
        total_rolls=("rolls", "sum"),
        total_data_gaps=("data_gaps", "sum"),
    )
    summary.to_csv(f"{PREFIX}_scenario_summary.csv", index=False)
    best_by_window = df.sort_values(["window", "return_pct"], ascending=[True, False]).groupby("window", as_index=False).head(1)
    best_by_window.to_csv(f"{PREFIX}_best_by_window.csv", index=False)
    print("Scenario summary:")
    print(summary.to_string(index=False))
    print("\nBest by window:")
    print(best_by_window[["window", "scenario", "return_pct", "max_drawdown_pct", "buy_hold_return_pct", "assigned_puts", "data_gaps"]].to_string(index=False))


if __name__ == "__main__":
    main()
