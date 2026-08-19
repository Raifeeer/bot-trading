from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu")
BACKTEST = ROOT / "backtests/failure_retest_backtests_2026-08-19.csv"
STATE = ROOT / "backtests/failure_retest_state_summary_2026-08-19.csv"
TRADES = ROOT / "backtests/failure_retest_backtest_trades_2026-08-19.csv"
OUT = ROOT / "backtests"


def main() -> None:
    frame = pd.read_csv(BACKTEST)
    baseline = frame[frame["variant"] == "baseline_day_breakout_s78"].copy()
    baseline = baseline.rename(columns={"return_pct": "baseline_return_pct", "max_drawdown_pct": "baseline_max_drawdown_pct", "trades": "baseline_trades"})[["window", "baseline_return_pct", "baseline_max_drawdown_pct", "baseline_trades"]]
    candidates = frame[frame["variant"] != "baseline_day_breakout_s78"].copy()
    comparison = candidates.merge(baseline, on="window", how="left")
    comparison["comparison_valid"] = ~((comparison["timeframe"] == "5min") & (comparison["window"] == "full_available"))
    comparison["delta_return_pp"] = comparison["return_pct"] - comparison["baseline_return_pct"]
    comparison["delta_drawdown_pp"] = comparison["max_drawdown_pct"] - comparison["baseline_max_drawdown_pct"]
    comparison["return_better"] = comparison["delta_return_pp"] > 0
    comparison["drawdown_no_worse"] = comparison["delta_drawdown_pp"] >= -0.25
    comparison["robust_pass"] = comparison["return_better"] & comparison["drawdown_no_worse"]
    valid = comparison[comparison["comparison_valid"]].copy()
    summary = valid.groupby(["variant", "timeframe"], as_index=False).agg(
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
    ).sort_values(["robust_windows", "positive_return_windows", "mean_delta_return_pp"], ascending=[False, False, False])
    states = pd.read_csv(STATE)
    state_summary = states.groupby(["variant", "timeframe"], as_index=False).agg(
        sequences=("sequences", "sum"),
        accepted=("accepted", "sum"),
        failed=("failed", "sum"),
        expired=("expired", "sum"),
    )
    state_summary["accepted_pct"] = state_summary["accepted"] / state_summary["sequences"].replace(0, pd.NA) * 100.0
    state_summary["failed_pct"] = state_summary["failed"] / state_summary["sequences"].replace(0, pd.NA) * 100.0
    summary = summary.merge(state_summary, on=["variant", "timeframe"], how="left")
    trades = pd.read_csv(TRADES)
    if not trades.empty:
        symbol_summary = trades.groupby(["variant", "symbol"], as_index=False).agg(trades=("pnl", "size"), pnl=("pnl", "sum"), wins=("pnl", lambda values: (values > 0).sum()), losses=("pnl", lambda values: (values < 0).sum()))
        symbol_summary["win_rate_pct"] = symbol_summary["wins"] / symbol_summary["trades"] * 100.0
    else:
        symbol_summary = pd.DataFrame()
    comparison.to_csv(OUT / "failure_retest_comparison_2026-08-19.csv", index=False)
    summary.to_csv(OUT / "failure_retest_variant_summary_2026-08-19.csv", index=False)
    state_summary.to_csv(OUT / "failure_retest_state_variant_summary_2026-08-19.csv", index=False)
    symbol_summary.to_csv(OUT / "failure_retest_symbol_summary_2026-08-19.csv", index=False)
    print("BASELINE")
    print(baseline.to_string(index=False))
    print("\nTOP SUMMARY")
    print(summary.to_string(index=False))
    print("\nFULL AVAILABLE")
    print(comparison[(comparison["window"] == "full_available") & comparison["comparison_valid"]].sort_values("delta_return_pp", ascending=False).to_string(index=False))
    print("\nSTATE SUMMARY")
    print(state_summary.sort_values(["accepted_pct", "sequences"], ascending=[False, False]).to_string(index=False))
    print("\nSYMBOL SUMMARY")
    print(symbol_summary.sort_values("pnl", ascending=False).head(80).to_string(index=False))


if __name__ == "__main__":
    main()
