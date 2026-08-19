"""Backtests de estrategias online seleccionadas.

BWB se evalúa como proxy diario con las barras reales de opciones disponibles.
0DTE/1DTE se reportan como gate de datos porque el cache no tiene quotes
intradía bid/ask ni timestamps de cutoff.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from run_defined_risk_backtests import (
    CAPITAL,
    DTE_TARGETS,
    HISTORY_DIR,
    MANAGEMENT,
    REGIME_MODES,
    SYMBOLS,
    WIDTHS,
    WINDOWS,
    _group_uses,
    _option_frame,
    _run,
)

OPTION_DIR = Path(os.environ.get("ONLINE_OPTION_HISTORY_DIR", "/home/ubuntu/backtests/online_option_history_2026-08-19"))
OUT = Path(os.environ.get("ONLINE_STRATEGY_BACKTEST_OUT", "/home/ubuntu/backtests/online_strategy_backtests_2026-08-19"))
STRUCTURES = ["bwb_call_credit", "bwb_put_credit"]


def _load_underlyings() -> dict[str, pd.DataFrame]:
    result = {}
    for symbol in SYMBOLS:
        path = HISTORY_DIR / f"{symbol}.pkl"
        if path.exists():
            frame = pd.read_pickle(path).copy()
            frame.index = pd.DatetimeIndex(frame.index).tz_convert("UTC")
            result[symbol] = frame.sort_index()
    return result


def main() -> None:
    underlyings = _load_underlyings()
    bars = pd.read_pickle(OPTION_DIR / "option_bars.pkl")
    bars_by_contract = {symbol: _option_frame(bars, symbol) for symbol in set(bars.index.get_level_values(0))}
    selected = json.loads((OPTION_DIR / "selected_contracts.json").read_text(encoding="utf-8"))
    groups = _group_uses(selected)
    rows = []
    curves = []
    events = []
    for structure in STRUCTURES:
        for dte in DTE_TARGETS:
            for width in WIDTHS:
                for management in MANAGEMENT:
                    for regime_mode in REGIME_MODES:
                        for window, (start, end) in WINDOWS.items():
                            metrics, curve, event_df = _run(underlyings, groups, bars_by_contract, structure, dte, width, management, regime_mode, start, end)
                            rows.append({"structure": structure, "dte_target": dte, "width": width, "management": management, "regime_mode": regime_mode, "window": window, "start": start, "end": end, **metrics})
                            if len(curve):
                                curve.insert(0, "structure", structure)
                                curve.insert(1, "dte_target", dte)
                                curve.insert(2, "width", width)
                                curve.insert(3, "management", management)
                                curve.insert(4, "regime_mode", regime_mode)
                                curve.insert(5, "window", window)
                                curves.append(curve)
                            if len(event_df):
                                event_df.insert(0, "structure", structure)
                                event_df.insert(1, "dte_target", dte)
                                event_df.insert(2, "width", width)
                                event_df.insert(3, "management", management)
                                event_df.insert(4, "regime_mode", regime_mode)
                                event_df.insert(5, "window", window)
                                events.append(event_df)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    result = pd.DataFrame(rows)
    result.to_csv(f"{OUT}_results.csv", index=False)
    pd.concat(curves, ignore_index=True).to_csv(f"{OUT}_equity_curves.csv", index=False) if curves else Path(f"{OUT}_equity_curves.csv").write_text("\n", encoding="utf-8")
    pd.concat(events, ignore_index=True).to_csv(f"{OUT}_events.csv", index=False) if events else Path(f"{OUT}_events.csv").write_text("\n", encoding="utf-8")
    source_manifest = json.loads((OPTION_DIR / "manifest.json").read_text(encoding="utf-8"))
    manifest = {"source": source_manifest, "capital": CAPITAL, "structures": STRUCTURES, "dte_targets": DTE_TARGETS, "widths": WIDTHS, "management": MANAGEMENT, "regime_modes": REGIME_MODES, "windows": WINDOWS, "bwb_status": "RESEARCH_ONLY_daily_proxy", "zero_dte_status": "REJECT_DATA_no_intraday_bid_ask_cutoff", "one_dte_status": "REJECT_DATA_no_intraday_bid_ask_cutoff", "intraday_quotes_required": True, "results_csv": f"{OUT}_results.csv"}
    Path(f"{OUT}_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"rows={len(result)}")
    print(result.groupby("structure")["return_pct"].agg(["mean", "min", "max"]).to_string())


if __name__ == "__main__":
    main()
