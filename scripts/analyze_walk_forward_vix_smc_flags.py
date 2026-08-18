"""Summarize non-overlapping walk-forward results without re-fitting parameters."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path("/home/ubuntu/backtests")
INPUT = ROOT / "walk_forward_vix_smc_flags_2026-08-18.csv"
OUTPUT = ROOT / "walk_forward_vix_smc_flags_2026-08-18_family_summary.csv"


def _compound(values: pd.Series) -> float:
    return float(((1.0 + values.astype(float) / 100.0).prod() - 1.0) * 100.0)


def main() -> None:
    frame = pd.read_csv(INPUT)
    rows: list[dict[str, object]] = []
    for family, group in frame.groupby("family", sort=True):
        return_wins = int(group["test_beats_return"].sum())
        dd_improvements = int((group["test_delta_drawdown_pp"] < 0).sum())
        rows.append({
            "family": family,
            "folds": len(group),
            "return_wins": return_wins,
            "drawdown_improvements": dd_improvements,
            "mean_test_delta_return_pp": float(group["test_delta_return_pp"].mean()),
            "mean_test_delta_drawdown_pp": float(group["test_delta_drawdown_pp"].mean()),
            "compound_selected_test_return_pct": _compound(group["test_return_pct"]),
            "compound_baseline_test_return_pct": _compound(group["baseline_test_return_pct"]),
            "mean_selected_trades": float(group["test_trades"].mean()),
            "mean_baseline_trades": float(group["baseline_test_trades"].mean()),
            "mean_trade_ratio": float((group["test_trades"] / group["baseline_test_trades"]).mean()),
            "selected_variants": ",".join(group["selected_variant"].astype(str)),
            "promotion_eligible": bool(return_wins >= 3
                                       and dd_improvements >= 2
                                       and group["mean_test_delta_return_pp"].mean() > 0
                                       and group["mean_test_delta_drawdown_pp"].mean() <= 0),
        })
    result = pd.DataFrame(rows)
    result.to_csv(OUTPUT, index=False)
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
