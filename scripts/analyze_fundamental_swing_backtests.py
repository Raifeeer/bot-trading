"""Summarize point-in-time fundamental filter backtests."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu/backtests")


def main() -> None:
    df = pd.read_csv(ROOT / "fundamental_swing_backtests_2026-08-18_results.csv")
    base = df[df["variant"] == "baseline"].set_index("window")
    rows = []
    for _, row in df.iterrows():
        reference = base.loc[row["window"]]
        rows.append({**row.to_dict(),
                     "delta_return_vs_baseline": row["return_pct"] - reference["return_pct"],
                     "delta_drawdown_vs_baseline": row["drawdown_pct"] - reference["drawdown_pct"],
                     "beats_return": row["return_pct"] > reference["return_pct"] + 1e-12,
                     "not_worse_drawdown": row["drawdown_pct"] >= reference["drawdown_pct"] - 0.25})
    deltas = pd.DataFrame(rows)
    deltas.to_csv(ROOT / "fundamental_swing_backtests_2026-08-18_deltas.csv", index=False)
    summary = deltas.groupby("variant").agg(
        mean_return=("return_pct", "mean"),
        mean_delta_return=("delta_return_vs_baseline", "mean"),
        mean_drawdown=("drawdown_pct", "mean"),
        mean_delta_drawdown=("delta_drawdown_vs_baseline", "mean"),
        windows_beating_return=("beats_return", "sum"),
        windows_not_worse_drawdown=("not_worse_drawdown", "sum"),
        mean_trades=("trades", "mean"),
        mean_win_rate=("win_rate_pct", "mean"),
    ).reset_index()
    summary.to_csv(ROOT / "fundamental_swing_backtests_2026-08-18_variant_summary.csv", index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
