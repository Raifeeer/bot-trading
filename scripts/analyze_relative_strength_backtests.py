"""Analiza la matriz relative strength contra benchmarks explícitos."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu")
BACKTEST = ROOT / "backtests/relative_strength_backtests_2026-08-19.csv"
OUT = ROOT / "backtests"


def main() -> None:
    frame = pd.read_csv(BACKTEST)
    baselines = frame[frame["variant"].isin(["baseline_equal_weight", "baseline_regime_s78"])].copy()
    candidates = frame[~frame["variant"].isin(["baseline_equal_weight", "baseline_regime_s78"])].copy()
    baseline_wide = baselines.pivot(
        index="window",
        columns="variant",
        values=["return_pct", "max_drawdown_pct"],
    )
    baseline_wide.columns = ["_".join(column) for column in baseline_wide.columns]
    comparison = candidates.merge(baseline_wide, left_on="window", right_index=True, how="left")
    comparison["delta_vs_equal_return_pp"] = comparison["return_pct"] - comparison["return_pct_baseline_equal_weight"]
    comparison["delta_vs_regime_return_pp"] = comparison["return_pct"] - comparison["return_pct_baseline_regime_s78"]
    comparison["delta_vs_equal_dd_pp"] = comparison["max_drawdown_pct"] - comparison["max_drawdown_pct_baseline_equal_weight"]
    comparison["delta_vs_regime_dd_pp"] = comparison["max_drawdown_pct"] - comparison["max_drawdown_pct_baseline_regime_s78"]
    comparison["better_than_regime"] = comparison["delta_vs_regime_return_pp"] > 0
    comparison["dd_not_worse_than_regime"] = comparison["delta_vs_regime_dd_pp"] >= -0.25
    comparison["robust_vs_regime"] = comparison["better_than_regime"] & comparison["dd_not_worse_than_regime"]
    comparison["full_window"] = comparison["window"] == "full_available"
    summary = (
        comparison.groupby("variant", as_index=False)
        .agg(
            windows=("window", "nunique"),
            positive_vs_regime_windows=("better_than_regime", "sum"),
            robust_vs_regime_windows=("robust_vs_regime", "sum"),
            mean_delta_vs_regime_return_pp=("delta_vs_regime_return_pp", "mean"),
            median_delta_vs_regime_return_pp=("delta_vs_regime_return_pp", "median"),
            mean_delta_vs_regime_dd_pp=("delta_vs_regime_dd_pp", "mean"),
            worst_delta_vs_regime_return_pp=("delta_vs_regime_return_pp", "min"),
            mean_return_pct=("return_pct", "mean"),
            mean_drawdown_pct=("max_drawdown_pct", "mean"),
            full_return_pct=("return_pct", lambda values: float(values[comparison.loc[values.index, "full_window"]].iloc[0]) if comparison.loc[values.index, "full_window"].any() else float("nan")),
            full_drawdown_pct=("max_drawdown_pct", lambda values: float(values[comparison.loc[values.index, "full_window"]].iloc[0]) if comparison.loc[values.index, "full_window"].any() else float("nan")),
            mean_turnover=("turnover_one_way", "mean"),
            mean_rebalances=("rebalances", "mean"),
            mean_abs_exposure=("mean_abs_exposure", "mean"),
        )
    )
    summary = summary.sort_values(
        ["robust_vs_regime_windows", "positive_vs_regime_windows", "mean_delta_vs_regime_return_pp"],
        ascending=[False, False, False],
    )
    sensitivity = (
        comparison.groupby(["horizon", "top_k", "rebalance_days", "gate", "mode", "only_positive", "cost_bps"], as_index=False)
        .agg(
            mean_return_pct=("return_pct", "mean"),
            mean_drawdown_pct=("max_drawdown_pct", "mean"),
            mean_delta_vs_regime_return_pp=("delta_vs_regime_return_pp", "mean"),
            robust_windows=("robust_vs_regime", "sum"),
            mean_turnover=("turnover_one_way", "mean"),
        )
        .sort_values("mean_delta_vs_regime_return_pp", ascending=False)
    )
    comparison.to_csv(OUT / "relative_strength_backtest_comparison_2026-08-19.csv", index=False)
    summary.to_csv(OUT / "relative_strength_backtest_variant_summary_2026-08-19.csv", index=False)
    sensitivity.to_csv(OUT / "relative_strength_backtest_sensitivity_2026-08-19.csv", index=False)
    print("BASELINES")
    print(baselines.to_string(index=False))
    print("\nTOP SUMMARY")
    print(summary.head(40).to_string(index=False))
    print("\nSENSITIVITY")
    print(sensitivity.head(40).to_string(index=False))


if __name__ == "__main__":
    main()
