"""Resumen reproducible del backtest de estructura MTF."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

INPUT = Path("/home/ubuntu/backtests/structure_mtf_backtests_2026-08-19.csv")
OUT = Path("/home/ubuntu/backtests/structure_mtf_backtests_2026-08-19_summary.csv")


def main() -> None:
    df = pd.read_csv(INPUT)
    baseline = df[df["variant"] == "baseline"][[
        "window", "return_pct", "max_drawdown_pct", "trades",
    ]].rename(columns={
        "return_pct": "baseline_return_pct",
        "max_drawdown_pct": "baseline_drawdown_pct",
        "trades": "baseline_trades",
    })
    candidates = df[df["variant"] != "baseline"].merge(baseline, on="window", how="left")
    candidates["return_delta_pp"] = candidates["return_pct"] - candidates["baseline_return_pct"]
    candidates["drawdown_delta_pp"] = candidates["max_drawdown_pct"] - candidates["baseline_drawdown_pct"]
    candidates["trades_delta"] = candidates["trades"] - candidates["baseline_trades"]
    candidates.to_csv(OUT, index=False)
    summary = candidates.groupby("variant", as_index=False).agg(
        windows=("window", "count"),
        mean_return_delta_pp=("return_delta_pp", "mean"),
        median_return_delta_pp=("return_delta_pp", "median"),
        mean_drawdown_delta_pp=("drawdown_delta_pp", "mean"),
        windows_return_positive=("return_delta_pp", lambda s: int((s > 0).sum())),
        windows_drawdown_improved=("drawdown_delta_pp", lambda s: int((s > 0).sum())),
        total_trades=("trades", "sum"),
    )
    summary.to_csv(OUT.with_name("structure_mtf_backtests_2026-08-19_variant_summary.csv"), index=False)
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
