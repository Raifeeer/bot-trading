"""Analiza Breakout20/55 con volumen frente a DayBreakout."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu")
BACKTEST = ROOT / "backtests/breakout_20_55_backtests_2026-08-19.csv"
TRADES = ROOT / "backtests/breakout_20_55_backtest_trades_2026-08-19.csv"
OUT = ROOT / "backtests"


def main() -> None:
    frame = pd.read_csv(BACKTEST)
    baseline = frame[frame["variant"] == "baseline_day_breakout_s78"].copy()
    candidates = frame[frame["variant"] != "baseline_day_breakout_s78"].copy()
    baseline = baseline.rename(
        columns={
            "return_pct": "baseline_return_pct",
            "max_drawdown_pct": "baseline_max_drawdown_pct",
            "trades": "baseline_trades",
        }
    )[["timeframe", "window", "baseline_return_pct", "baseline_max_drawdown_pct", "baseline_trades"]]
    comparison = candidates.merge(baseline.drop(columns=["timeframe"]), on=["window"], how="left")
    comparison["comparison_valid"] = ~((comparison["timeframe"] == "5min") & (comparison["window"] == "full_available"))
    comparison["delta_return_pp"] = comparison["return_pct"] - comparison["baseline_return_pct"]
    comparison["delta_drawdown_pp"] = comparison["max_drawdown_pct"] - comparison["baseline_max_drawdown_pct"]
    comparison["return_better"] = comparison["delta_return_pp"] > 0
    comparison["drawdown_no_worse"] = comparison["delta_drawdown_pp"] >= -0.25
    comparison["robust_pass"] = comparison["return_better"] & comparison["drawdown_no_worse"]
    valid = comparison[comparison["comparison_valid"]].copy()
    summary = (
        valid.groupby(["variant", "timeframe"], as_index=False)
        .agg(
            windows=("window", "nunique"),
            positive_return_windows=("return_better", "sum"),
            robust_windows=("robust_pass", "sum"),
            mean_delta_return_pp=("delta_return_pp", "mean"),
            median_delta_return_pp=("delta_return_pp", "median"),
            mean_delta_drawdown_pp=("delta_drawdown_pp", "mean"),
            worst_delta_return_pp=("delta_return_pp", "min"),
            total_trades=("trades", "sum"),
            total_signals=("signals", "sum"),
            mean_win_rate_pct=("win_rate_pct", "mean"),
            mean_profit_factor=("profit_factor", "mean"),
        )
        .sort_values(["robust_windows", "positive_return_windows", "mean_delta_return_pp"], ascending=[False, False, False])
    )
    trades = pd.read_csv(TRADES)
    if not trades.empty:
        trades["pnl"] = pd.to_numeric(trades["pnl"], errors="coerce").fillna(0.0)
        symbol_summary = (
            trades.groupby(["variant", "symbol"], as_index=False)
            .agg(trades=("pnl", "size"), pnl=("pnl", "sum"), wins=("pnl", lambda values: (values > 0).sum()), losses=("pnl", lambda values: (values < 0).sum()))
        )
        symbol_summary["win_rate_pct"] = symbol_summary["wins"] / symbol_summary["trades"] * 100.0
    else:
        symbol_summary = pd.DataFrame()
    comparison.to_csv(OUT / "breakout_20_55_backtest_comparison_2026-08-19.csv", index=False)
    summary.to_csv(OUT / "breakout_20_55_backtest_variant_summary_2026-08-19.csv", index=False)
    symbol_summary.to_csv(OUT / "breakout_20_55_backtest_symbol_summary_2026-08-19.csv", index=False)
    print("BASELINE")
    print(baseline.to_string(index=False))
    print("\nTOP SUMMARY")
    print(summary.to_string(index=False))
    print("\nFULL AVAILABLE")
    print(comparison[(comparison["window"] == "full_available") & comparison["comparison_valid"]].sort_values("delta_return_pp", ascending=False).to_string(index=False))
    print("\nSYMBOL SUMMARY")
    print(symbol_summary.sort_values("pnl", ascending=False).head(80).to_string(index=False))


if __name__ == "__main__":
    main()
