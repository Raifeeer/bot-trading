from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from scripts.run_failure_retest_backtests import accepted_for_simulation, scan_events
from scripts.run_orb_backtests import (
    DAILY_DIR,
    FIFTEEN_DIR,
    OUT_DIR,
    START_CAPITAL,
    SYMBOLS,
    aggregate_curves,
    build_regimes,
    load_pickle,
    metric_row,
    normalise,
    prepare_daybreakout,
    simulate_daybreakout,
)
from scripts.run_vwap_backtests import simulate_vwap_fast

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
CANDIDATES = [
    {"name": "failure_retest_15min_lb55_rt5_vol00_bull", "timeframe": "15min", "lookback": 55, "retest_max_bars": 5, "retest_tolerance_atr": 0.25, "volume_min": 0.0, "gate": "bull", "hold_max_bars": 20},
    {"name": "failure_retest_15min_lb55_rt3_vol00_bull", "timeframe": "15min", "lookback": 55, "retest_max_bars": 3, "retest_tolerance_atr": 0.25, "volume_min": 0.0, "gate": "bull", "hold_max_bars": 20},
    {"name": "failure_retest_15min_lb55_rt5_vol10_bull", "timeframe": "15min", "lookback": 55, "retest_max_bars": 5, "retest_tolerance_atr": 0.25, "volume_min": 1.0, "gate": "bull", "hold_max_bars": 20},
    {"name": "failure_retest_15min_lb20_rt3_vol00_bull", "timeframe": "15min", "lookback": 20, "retest_max_bars": 3, "retest_tolerance_atr": 0.25, "volume_min": 0.0, "gate": "bull", "hold_max_bars": 20},
]


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    symbols = [symbol for symbol in SYMBOLS if daily[symbol] is not None and fifteen[symbol] is not None]
    regimes = build_regimes({symbol: daily[symbol] for symbol in symbols}, symbols)
    all_dates = sorted({str(day) for symbol in symbols for day in fifteen[symbol]["session_date"].unique()})
    evaluation_dates = all_dates[25:]
    fold_count = 5 if len(evaluation_dates) >= 100 else max(3, len(evaluation_dates) // 20)
    fold_size = len(evaluation_dates) // fold_count
    usable_dates = evaluation_dates[-fold_count * fold_size :]
    folds = {f"fold_{index + 1}": usable_dates[index * fold_size : (index + 1) * fold_size] for index in range(fold_count)}
    prepared = {symbol: prepare_daybreakout(fifteen[symbol], params) for symbol in symbols}
    cache = {candidate["name"]: {symbol: scan_events(fifteen[symbol], candidate) for symbol in symbols} for candidate in CANDIDATES}
    rows: list[dict] = []
    for fold_name, dates in folds.items():
        base_curves, base_trades = [], []
        for symbol in symbols:
            curve, trades = simulate_daybreakout(symbol, prepared[symbol], dates, params, regimes, START_CAPITAL / len(symbols))
            if not curve.empty:
                base_curves.append(curve)
            base_trades.extend(trades)
        base = metric_row(aggregate_curves(base_curves), base_trades, "baseline_day_breakout_s78", "15min", fold_name, 0)
        rows.append(base)
        for candidate in CANDIDATES:
            curves, trades = [], []
            accepted = failed = expired = 0
            for symbol in symbols:
                events = [event for event in cache[candidate["name"]][symbol] if dates[0] <= event["session_date"] <= dates[-1]]
                if candidate["gate"] == "bull":
                    events = [event for event in events if event["status"] != "accepted" or regimes.get(event["session_date"], {}).get("regime") == "bull"]
                accepted += sum(event["status"] == "accepted" for event in events)
                failed += sum(event["status"] == "failed" for event in events)
                expired += sum(event["status"] == "expired" for event in events)
                entries = [accepted_for_simulation(event) for event in events if event["status"] == "accepted"]
                curve, symbol_trades = simulate_vwap_fast(symbol, fifteen[symbol], entries, dates, START_CAPITAL / len(symbols), candidate["hold_max_bars"])
                if not curve.empty:
                    curves.append(curve)
                trades.extend(symbol_trades)
            row = metric_row(aggregate_curves(curves), trades, candidate["name"], "15min", fold_name, accepted)
            row.update({"accepted": accepted, "failed": failed, "expired": expired, "delta_return_pp": row["return_pct"] - base["return_pct"], "delta_drawdown_pp": row["max_drawdown_pct"] - base["max_drawdown_pct"]})
            rows.append(row)
    output = OUT_DIR / "failure_retest_walkforward_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    with open(OUT_DIR / "failure_retest_walkforward_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump({"folds": folds, "candidates": CANDIDATES, "symbols": symbols, "output": str(output)}, handle, indent=2)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
