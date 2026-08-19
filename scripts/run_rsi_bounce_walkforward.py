from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from scripts.run_orb_backtests import (
    DAILY_DIR,
    FIFTEEN_DIR,
    OUT_DIR,
    START_CAPITAL,
    SYMBOLS,
    aggregate_curves,
    build_regimes,
    gate_allows,
    load_pickle,
    metric_row,
    normalise,
    prepare_daybreakout,
    simulate_daybreakout,
)
from scripts.run_rsi_bounce_backtests import scan_events
from scripts.run_vwap_backtests import simulate_vwap_fast

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
CANDIDATES = [
    {
        "name": "rsi_15min_p2_t30_sma0_bull",
        "timeframe": "15min",
        "rsi_period": 2,
        "oversold_threshold": 30.0,
        "require_sma_fast_above_trend": False,
        "gate": "bull",
        "hold_max_bars": 20,
    },
    {
        "name": "rsi_15min_p5_t20_sma0_bull",
        "timeframe": "15min",
        "rsi_period": 5,
        "oversold_threshold": 20.0,
        "require_sma_fast_above_trend": False,
        "gate": "bull",
        "hold_max_bars": 20,
    },
    {
        "name": "rsi_15min_p14_t30_sma0_bull",
        "timeframe": "15min",
        "rsi_period": 14,
        "oversold_threshold": 30.0,
        "require_sma_fast_above_trend": False,
        "gate": "bull",
        "hold_max_bars": 20,
    },
    {
        "name": "rsi_15min_p14_t20_sma0_none",
        "timeframe": "15min",
        "rsi_period": 14,
        "oversold_threshold": 20.0,
        "require_sma_fast_above_trend": False,
        "gate": "none",
        "hold_max_bars": 20,
    },
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
    warmup_sessions = 20
    evaluation_dates = all_dates[warmup_sessions:]
    fold_count = 5 if len(evaluation_dates) >= 100 else max(3, len(evaluation_dates) // 20)
    fold_size = len(evaluation_dates) // fold_count
    usable_dates = evaluation_dates[-fold_count * fold_size :]
    folds = {
        f"fold_{index + 1}": usable_dates[index * fold_size : (index + 1) * fold_size]
        for index in range(fold_count)
    }
    prepared = {symbol: prepare_daybreakout(fifteen[symbol], params) for symbol in symbols}
    event_cache = {
        candidate["name"]: {
            symbol: scan_events(fifteen[symbol], candidate) for symbol in symbols
        }
        for candidate in CANDIDATES
    }
    rows: list[dict] = []
    for fold_name, dates in folds.items():
        base_curves, base_trades = [], []
        for symbol in symbols:
            curve, trades = simulate_daybreakout(symbol, prepared[symbol], dates, params, regimes, START_CAPITAL / len(symbols))
            if not curve.empty:
                base_curves.append(curve)
            base_trades.extend(trades)
        rows.append(metric_row(aggregate_curves(base_curves), base_trades, "baseline_day_breakout_s78", "15min", fold_name, 0))
        baseline_return = rows[-1]["return_pct"]
        baseline_dd = rows[-1]["max_drawdown_pct"]
        for candidate in CANDIDATES:
            curves, trades = [], []
            signals = 0
            for symbol in symbols:
                events = [event for event in event_cache[candidate["name"]][symbol] if dates[0] <= event["session_date"] <= dates[-1] and gate_allows(event, candidate["gate"], regimes)]
                signals += len(events)
                curve, symbol_trades = simulate_vwap_fast(symbol, fifteen[symbol], events, dates, START_CAPITAL / len(symbols), candidate["hold_max_bars"])
                if not curve.empty:
                    curves.append(curve)
                trades.extend(symbol_trades)
            result = metric_row(aggregate_curves(curves), trades, candidate["name"], "15min", fold_name, signals)
            result["delta_return_pp"] = result["return_pct"] - baseline_return
            result["delta_drawdown_pp"] = result["max_drawdown_pct"] - baseline_dd
            rows.append(result)
    output = OUT_DIR / "rsi_bounce_walkforward_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    manifest = {"folds": folds, "candidates": CANDIDATES, "symbols": symbols, "output": str(output), "cost_bps_per_side": 5.0}
    with open(OUT_DIR / "rsi_bounce_walkforward_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
