"""Analiza la matriz de estrategias de riesgo definido sin overfitting de una ventana."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RESULTS = Path("/home/ubuntu/backtests/defined_risk_backtests_2026-08-18_results.csv")
PREFIX = Path("/home/ubuntu/backtests/defined_risk_backtests_2026-08-18")
KEYS = ["structure", "dte_target", "width", "management", "regime_mode"]


def main() -> None:
    df = pd.read_csv(RESULTS)
    df["profitable"] = df["return_pct"] > 0
    df["beats_buy_hold"] = df["return_pct"] > df["buy_hold_return_pct"]
    summary = df.groupby(KEYS, as_index=False).agg(
        windows=("window", "count"),
        mean_return_pct=("return_pct", "mean"),
        median_return_pct=("return_pct", "median"),
        worst_return_pct=("return_pct", "min"),
        best_return_pct=("return_pct", "max"),
        mean_drawdown_pct=("max_drawdown_pct", "mean"),
        worst_drawdown_pct=("max_drawdown_pct", "min"),
        profitable_windows=("profitable", "sum"),
        beats_buy_hold_windows=("beats_buy_hold", "sum"),
        mean_win_rate_pct=("win_rate_pct", "mean"),
        mean_profit_factor=("profit_factor", "mean"),
        total_max_loss_hits=("max_loss_hits", "sum"),
        total_data_gaps=("data_gaps", "sum"),
        total_commissions=("commissions", "sum"),
    )
    summary["stability_score"] = (
        summary["profitable_windows"] * 2
        + summary["beats_buy_hold_windows"]
        + (summary["worst_return_pct"] > 0).astype(int) * 2
        - (summary["worst_drawdown_pct"].abs() > 5).astype(int) * 2
        - (summary["total_data_gaps"] > 20).astype(int) * 2
    )
    summary.sort_values(["stability_score", "mean_return_pct", "worst_return_pct"], ascending=False).to_csv(f"{PREFIX}_summary.csv", index=False)
    robust = summary[(summary["profitable_windows"] >= 4) & (summary["worst_return_pct"] > -1.0) & (summary["total_data_gaps"] <= 20)].sort_values(["mean_return_pct", "worst_return_pct"], ascending=False)
    robust.to_csv(f"{PREFIX}_robust_candidates.csv", index=False)
    top_full = df.sort_values("return_pct", ascending=False).head(30)
    top_full.to_csv(f"{PREFIX}_top_full_window.csv", index=False)
    print("Robust candidates:")
    print(robust.head(30).to_string(index=False))
    print("\nTop full_recent rows:")
    print(df[df["window"] == "full_recent"].sort_values("return_pct", ascending=False).head(25).to_string(index=False))
    print("\nStructure-level summary:")
    print(df.groupby("structure", as_index=False).agg(mean_return_pct=("return_pct", "mean"), worst_return_pct=("return_pct", "min"), mean_drawdown_pct=("max_drawdown_pct", "mean"), profitable_windows=("profitable", "sum"), total_rows=("window", "count")).sort_values("mean_return_pct", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
