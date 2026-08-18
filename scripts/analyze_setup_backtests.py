"""Resume los artefactos del backtest de setups sin cambiar sus resultados."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

BASE = Path("/home/ubuntu/backtests")
RESULTS = BASE / "setup_confluence_backtests_2026-08-18.csv"
ACTIVITY = BASE / "setup_confluence_component_activity_2026-08-18.csv"
OUT = BASE / "setup_confluence_analysis_2026-08-18"


def main() -> None:
    df = pd.read_csv(RESULTS)
    rows = []
    for window in sorted(df["window"].unique()):
        base = df[(df.window == window) & (df.scenario == "buy_hold")].iloc[0]
        for scenario in ("setup_moderate", "setup_strict"):
            row = df[(df.window == window) & (df.scenario == scenario)].iloc[0]
            rows.append({
                "window": window,
                "scenario": scenario,
                "return_pct": row.return_pct,
                "return_delta_vs_buy_hold_pct": row.return_pct - base.return_pct,
                "drawdown_pct": row.max_drawdown_pct,
                "drawdown_delta_vs_buy_hold_pct": row.max_drawdown_pct - base.max_drawdown_pct,
                "profit_factor": row.profit_factor,
                "signals": row.signals,
                "trades": row.trades,
                "positive_days_pct": row.positive_days_pct,
            })
    comparison = pd.DataFrame(rows)
    comparison.to_csv(f"{OUT}_comparison.csv", index=False)

    activity = pd.read_csv(ACTIVITY)
    active = activity[(activity.scenario == "setup_moderate") & (activity.evaluations > 0)].copy()
    active["active_rate_pct"] = active.active / active.evaluations * 100.0
    component_summary = active.groupby("setup", as_index=False).agg(
        evaluations=("evaluations", "sum"),
        bull=("bull", "sum"),
        bear=("bear", "sum"),
        neutral=("neutral", "sum"),
        active=("active", "sum"),
    )
    component_summary["active_rate_pct"] = component_summary.active / component_summary.evaluations * 100.0
    component_summary["directional_rate_pct"] = (component_summary.bull + component_summary.bear) / component_summary.evaluations * 100.0
    component_summary = component_summary.sort_values(["active_rate_pct", "directional_rate_pct"], ascending=False)
    component_summary.to_csv(f"{OUT}_component_summary.csv", index=False)

    payload = {
        "comparison_csv": f"{OUT}_comparison.csv",
        "component_summary_csv": f"{OUT}_component_summary.csv",
        "best_return_by_window": comparison.loc[comparison.groupby("window").return_pct.idxmax()].to_dict("records"),
        "strict_beats_baseline_return_windows": comparison[(comparison.scenario == "setup_strict") & (comparison.return_delta_vs_buy_hold_pct > 0)].window.tolist(),
        "moderate_beats_baseline_return_windows": comparison[(comparison.scenario == "setup_moderate") & (comparison.return_delta_vs_buy_hold_pct > 0)].window.tolist(),
    }
    (BASE / "setup_confluence_analysis_2026-08-18.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(comparison.to_string(index=False))
    print("\nCOMPONENT SUMMARY")
    print(component_summary.to_string(index=False))


if __name__ == "__main__":
    main()
