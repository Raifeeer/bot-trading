"""Resumen determinista de la matriz current-policy + setups."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RESULTS = Path("/home/ubuntu/backtests/current_setup_integration_2026-08-18_results.csv")
OUT = Path("/home/ubuntu/backtests/current_setup_integration_2026-08-18")


def main() -> None:
    df = pd.read_csv(RESULTS)
    base = df[df.variant == "baseline_current"][["window", "return_pct", "max_drawdown_pct"]].rename(columns={"return_pct": "base_return_pct", "max_drawdown_pct": "base_dd_pct"})
    comp = df.merge(base, on="window", how="left")
    comp["delta_return_pct"] = comp["return_pct"] - comp["base_return_pct"]
    comp["delta_dd_pct"] = comp["max_drawdown_pct"] - comp["base_dd_pct"]
    comp["dd_improved"] = comp["delta_dd_pct"] >= 0
    comp["return_improved"] = comp["delta_return_pct"] > 0
    comp["profitable"] = comp["return_pct"] > 0
    comp["status"] = comp.apply(
        lambda row: "profit_and_dd_better" if row.return_improved and row.dd_improved else (
            "dd_better_only" if row.dd_improved else (
                "return_better_only" if row.return_improved else "worse_or_equal"
            )
        ), axis=1,
    )
    comparison = comp[comp.variant != "baseline_current"].copy()
    comparison.to_csv(f"{OUT}_comparison.csv", index=False)
    summary = comparison.groupby("variant", as_index=False).agg(
        windows=("window", "count"),
        return_delta_median_pct=("delta_return_pct", "median"),
        return_delta_mean_pct=("delta_return_pct", "mean"),
        dd_delta_median_pct=("delta_dd_pct", "median"),
        dd_improved_windows=("dd_improved", "sum"),
        return_improved_windows=("return_improved", "sum"),
        profitable_windows=("profitable", "sum"),
        total_trades=("trades", "sum"),
        total_signals=("signals", "sum"),
    )
    summary.to_csv(f"{OUT}_variant_summary.csv", index=False)
    best = comparison.sort_values(["delta_return_pct", "delta_dd_pct"], ascending=False).head(12)
    best.to_csv(f"{OUT}_top_deltas.csv", index=False)
    print(summary.to_string(index=False))
    print("\nComparación por ventana:")
    print(comparison[["window", "variant", "return_pct", "base_return_pct", "delta_return_pct", "max_drawdown_pct", "base_dd_pct", "delta_dd_pct", "status"]].to_string(index=False))


if __name__ == "__main__":
    main()
