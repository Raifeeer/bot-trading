from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.run_relative_strength_backtests import (
    DAILY_DIR,
    SYMBOLS,
    build_regimes,
    close_map,
    evaluate_relative_strength,
    load_pickle,
    normalise,
    simulate_variant,
)

ROOT = Path("/home/ubuntu")
OUT_DIR = ROOT / "backtests"

CANDIDATES = [
    {
        "name": "rs_h60_k2_r5_bull_long_only_all_c5",
        "horizon": 60,
        "top_k": 2,
        "rebalance_days": 5,
        "gate": "bull",
        "mode": "long_only",
        "only_positive": False,
        "cost_bps": 5.0,
    },
    {
        "name": "rs_h60_k2_r5_bull_long_only_all_c20",
        "horizon": 60,
        "top_k": 2,
        "rebalance_days": 5,
        "gate": "bull",
        "mode": "long_only",
        "only_positive": False,
        "cost_bps": 20.0,
    },
    {
        "name": "rs_h20_k1_r5_bull_long_only_all_c5",
        "horizon": 20,
        "top_k": 1,
        "rebalance_days": 5,
        "gate": "bull",
        "mode": "long_only",
        "only_positive": False,
        "cost_bps": 5.0,
    },
    {
        "name": "rs_h60_k2_r5_bull_long_short_all_c5",
        "horizon": 60,
        "top_k": 2,
        "rebalance_days": 5,
        "gate": "bull",
        "mode": "long_short",
        "only_positive": False,
        "cost_bps": 5.0,
    },
]


def baseline_curve(frames, symbols, regimes, dates, window_dates, mode):
    prices = close_map(frames, dates)
    first_idx, last_idx = dates.index(window_dates[0]), dates.index(window_dates[-1])
    equity = 100_000.0
    curve = {}
    for idx in range(first_idx, last_idx + 1):
        day = dates[idx]
        if idx > first_idx:
            prev = dates[idx - 1]
            state = regimes.get(prev, {}).get("regime", "cash")
            active = mode == "equal_weight" or state == "bull"
            if active:
                ret = sum(
                    (prices[symbol][day] / prices[symbol][prev] - 1.0) / len(symbols)
                    for symbol in symbols
                    if day in prices[symbol] and prev in prices[symbol]
                )
                equity *= 1.0 + ret
        curve[pd.Timestamp(day, tz="America/New_York").tz_convert("UTC")] = equity
    series = pd.Series(curve).sort_index()
    dd = float((series / series.cummax() - 1.0).min()) * 100.0
    return (float(series.iloc[-1]) / 100_000.0 - 1.0) * 100.0, dd


def main() -> None:
    raw = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    symbols = [symbol for symbol in SYMBOLS if raw[symbol] is not None]
    frames = {symbol: raw[symbol] for symbol in symbols}
    dates = sorted({day for frame in frames.values() for day in frame["session_date"].unique()})
    regimes = build_regimes(frames, symbols)
    horizons = {candidate["horizon"] for candidate in CANDIDATES}
    snapshots = {}
    for day in dates:
        asof = pd.Timestamp(day, tz="America/New_York").tz_convert("UTC") + pd.Timedelta(hours=23)
        for horizon in horizons:
            snapshots[(day, horizon)] = evaluate_relative_strength(
                frames,
                horizon_bars=horizon,
                top_percentile=0.75,
                bottom_percentile=0.25,
                only_positive=False,
                allow_shorts=True,
                asof_timestamp=asof,
            )["observations"]
    fold_count = min(4, len(dates) // 60)
    folds = {
        f"fold_{idx + 1}": dates[-60 * (idx + 1) : -60 * idx if idx else None]
        for idx in range(fold_count)
    }
    folds = dict(reversed(list(folds.items())))
    rows = []
    for fold_name, fold_dates in folds.items():
        regime_return, regime_dd = baseline_curve(frames, symbols, regimes, dates, fold_dates, "regime")
        equal_return, equal_dd = baseline_curve(frames, symbols, regimes, dates, fold_dates, "equal_weight")
        rows.extend(
            [
                {"variant": "baseline_regime_s78", "fold": fold_name, "return_pct": regime_return, "max_drawdown_pct": regime_dd, "delta_vs_regime_pp": 0.0, "delta_vs_equal_pp": regime_return - equal_return},
                {"variant": "baseline_equal_weight", "fold": fold_name, "return_pct": equal_return, "max_drawdown_pct": equal_dd, "delta_vs_regime_pp": equal_return - regime_return, "delta_vs_equal_pp": 0.0},
            ]
        )
        for candidate in CANDIDATES:
            curve, extra = simulate_variant(
                frames,
                dates,
                fold_dates,
                regimes,
                snapshots,
                horizon=candidate["horizon"],
                top_k=candidate["top_k"],
                rebalance_days=candidate["rebalance_days"],
                gate=candidate["gate"],
                mode=candidate["mode"],
                only_positive=candidate["only_positive"],
                cost_bps=candidate["cost_bps"],
            )
            ret = (float(curve.iloc[-1]) / 100_000.0 - 1.0) * 100.0
            dd = float((curve / curve.cummax() - 1.0).min()) * 100.0
            rows.append(
                {
                    "variant": candidate["name"],
                    "fold": fold_name,
                    "return_pct": ret,
                    "max_drawdown_pct": dd,
                    "delta_vs_regime_pp": ret - regime_return,
                    "delta_vs_equal_pp": ret - equal_return,
                    **extra,
                }
            )
    output = OUT_DIR / "relative_strength_walkforward_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    with open(OUT_DIR / "relative_strength_walkforward_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump({"folds": {key: value for key, value in folds.items()}, "candidates": CANDIDATES, "symbols": symbols, "output": str(output)}, handle, indent=2)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
