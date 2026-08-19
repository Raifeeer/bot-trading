"""Resume la matriz de estrategias online sin seleccionar por máximo puntual."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

RESULTS = Path("/home/ubuntu/backtests/online_strategy_backtests_2026-08-19_results.csv")
OPTION_MANIFEST = Path("/home/ubuntu/backtests/online_option_history_2026-08-19/manifest.json")
OUT = Path("/home/ubuntu/backtests/online_strategy_backtests_2026-08-19")


def main() -> None:
    frame = pd.read_csv(RESULTS)
    summary = frame.groupby("structure").agg(mean_return_pct=("return_pct", "mean"), median_return_pct=("return_pct", "median"), min_return_pct=("return_pct", "min"), mean_drawdown_pct=("max_drawdown_pct", "mean"), median_drawdown_pct=("max_drawdown_pct", "median"), mean_trades=("closed_trades", "mean"), mean_gaps=("data_gaps", "mean"), windows_positive=("return_pct", lambda values: int((values > 0).sum())), total_rows=("return_pct", "size")).reset_index()
    window_summary = frame.groupby(["structure", "window"]).agg(mean_return_pct=("return_pct", "mean"), mean_drawdown_pct=("max_drawdown_pct", "mean"), mean_trades=("closed_trades", "mean"), min_return_pct=("return_pct", "min"), max_return_pct=("return_pct", "max")).reset_index()
    frame["buy_hold_delta_pp"] = frame["return_pct"] - frame["buy_hold_return_pct"]
    delta_summary = frame.groupby("structure").agg(mean_delta_vs_buy_hold_pp=("buy_hold_delta_pp", "mean"), median_delta_vs_buy_hold_pp=("buy_hold_delta_pp", "median"), rows_better_than_buy_hold=("buy_hold_delta_pp", lambda values: int((values > 0).sum())), rows_total=("buy_hold_delta_pp", "size")).reset_index()
    summary.to_csv(f"{OUT}_summary.csv", index=False)
    window_summary.to_csv(f"{OUT}_window_summary.csv", index=False)
    delta_summary.to_csv(f"{OUT}_delta_summary.csv", index=False)
    manifest = json.loads(OPTION_MANIFEST.read_text(encoding="utf-8"))
    report = {"summary": summary.to_dict(orient="records"), "window_summary": window_summary.to_dict(orient="records"), "delta_summary": delta_summary.to_dict(orient="records"), "data_manifest": manifest, "zero_dte_decision": "REJECT_DATA_intraday_bid_ask_and_cutoff_missing", "one_dte_decision": "REJECT_DATA_intraday_bid_ask_and_cutoff_missing", "bwb_decision": "RESEARCH_ONLY_daily_option_proxy_until_bid_ask_and_assignment_are_available"}
    Path(f"{OUT}_analysis.json").write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(summary.to_string(index=False))
    print("\nPor ventana:")
    print(window_summary.to_string(index=False))
    print("\nDelta frente a buy-and-hold:")
    print(delta_summary.to_string(index=False))


if __name__ == "__main__":
    main()
