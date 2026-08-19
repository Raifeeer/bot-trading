from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from scripts.run_intraday_mean_reversion_backtests import accepted_events, scan
from scripts.run_orb_backtests import (
    DAILY_DIR,
    FIFTEEN_DIR,
    OUT_DIR,
    START_CAPITAL,
    SYMBOLS,
    aggregate_curves,
    build_regimes,
    date_key,
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
    {"name": "mr_15min_ext20_rec025_bull", "timeframe": "15min", "extension_atr": 2.0, "reclaim_atr": 0.25, "gate": "bull", "hold_max_bars": 20},
    {"name": "mr_15min_ext10_rec025_bull", "timeframe": "15min", "extension_atr": 1.0, "reclaim_atr": 0.25, "gate": "bull", "hold_max_bars": 20},
    {"name": "mr_15min_ext20_rec05_bull", "timeframe": "15min", "extension_atr": 2.0, "reclaim_atr": 0.5, "gate": "bull", "hold_max_bars": 20},
    {"name": "mr_15min_ext15_rec025_bull", "timeframe": "15min", "extension_atr": 1.5, "reclaim_atr": 0.25, "gate": "bull", "hold_max_bars": 20},
]


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    symbols = [symbol for symbol in SYMBOLS if daily[symbol] is not None and fifteen[symbol] is not None]
    regimes = build_regimes({symbol: daily[symbol] for symbol in symbols}, symbols)
    all_dates = sorted({date_key(index) for symbol in symbols for index in fifteen[symbol].index})
    evaluation_dates = all_dates[25:]
    fold_count = 5 if len(evaluation_dates) >= 100 else max(3, len(evaluation_dates) // 20)
    fold_size = len(evaluation_dates) // fold_count
    usable = evaluation_dates[-fold_count * fold_size :]
    folds = {f"fold_{index + 1}": usable[index * fold_size : (index + 1) * fold_size] for index in range(fold_count)}
    prepared = {symbol: prepare_daybreakout(fifteen[symbol], params) for symbol in symbols}
    cache = {candidate["name"]: {symbol: scan(fifteen[symbol], candidate, regimes) for symbol in symbols} for candidate in CANDIDATES}
    rows = []
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
            extensions = confirmed = no_reclaim = no_edge = 0
            for symbol in symbols:
                events = [event for event in cache[candidate["name"]][symbol] if dates[0] <= event.get("session_date", "") <= dates[-1]]
                extensions += len(events)
                confirmed += sum(event.get("status") == "confirmed" for event in events)
                no_reclaim += sum(event.get("status") == "extension_no_reclaim" for event in events)
                no_edge += sum(event.get("status") == "confirmation_no_edge" for event in events)
                curve, symbol_trades = simulate_vwap_fast(symbol, fifteen[symbol], accepted_events(events), dates, START_CAPITAL / len(symbols), candidate["hold_max_bars"])
                if not curve.empty:
                    curves.append(curve)
                trades.extend(symbol_trades)
            row = metric_row(aggregate_curves(curves), trades, candidate["name"], "15min", fold_name, confirmed)
            row.update({"extensions": extensions, "confirmed": confirmed, "no_reclaim": no_reclaim, "no_edge": no_edge, "delta_return_pp": row["return_pct"] - base["return_pct"], "delta_drawdown_pp": row["max_drawdown_pct"] - base["max_drawdown_pct"]})
            rows.append(row)
    output = OUT_DIR / "intraday_mean_reversion_walkforward_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    with open(OUT_DIR / "intraday_mean_reversion_walkforward_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump({"folds": folds, "candidates": CANDIDATES, "symbols": symbols, "output": str(output)}, handle, indent=2)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
