"""Resumen reproducible de resultados SMC ampliado."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu/backtests")


def main() -> None:
    df = pd.read_csv(ROOT / "smc_expanded_backtests_2026-08-18_results.csv")
    metrics = ["return_pct", "drawdown_pct", "trades", "win_rate_pct", "profit_factor"]
    grouped = df.groupby(["window", "variant"], as_index=False)[metrics].mean()
    base = grouped[grouped["variant"] == "baseline"].set_index("window")
    rows = []
    for _, row in grouped.iterrows():
        b = base.loc[row["window"]]
        rows.append({**row.to_dict(),
                     "delta_return_vs_baseline": row["return_pct"] - b["return_pct"],
                     "delta_drawdown_vs_baseline": row["drawdown_pct"] - b["drawdown_pct"],
                     "beats_return": bool(row["return_pct"] > b["return_pct"] + 1e-12),
                     "not_worse_drawdown": bool(row["drawdown_pct"] >= b["drawdown_pct"] - 0.25)})
    deltas = pd.DataFrame(rows)
    deltas.to_csv(ROOT / "smc_expanded_backtests_2026-08-18_deltas.csv", index=False)
    summary = deltas.groupby("variant").agg(
        mean_delta_return=("delta_return_vs_baseline", "mean"),
        mean_delta_drawdown=("delta_drawdown_vs_baseline", "mean"),
        windows_beating_return=("beats_return", "sum"),
        windows_not_worse_drawdown=("not_worse_drawdown", "sum"),
        mean_trades=("trades", "mean"),
        mean_win_rate=("win_rate_pct", "mean"),
    ).reset_index()
    summary.to_csv(ROOT / "smc_expanded_backtests_2026-08-18_variant_summary.csv", index=False)
    robust = summary[(summary["windows_beating_return"] >= 3)
                     & (summary["windows_not_worse_drawdown"] >= 3)]
    robust.to_csv(ROOT / "smc_expanded_backtests_2026-08-18_robust_candidates.csv", index=False)
    print("--- variant summary")
    print(summary.to_string(index=False))
    print("--- robust candidates")
    print(robust.to_string(index=False))


if __name__ == "__main__":
    main()
