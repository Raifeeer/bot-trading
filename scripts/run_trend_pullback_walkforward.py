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
    normalise,
    prepare_daybreakout,
    simulate_daybreakout,
)
from scripts.run_vwap_backtests import simulate_vwap_fast
from strategies.trend_pullback_continuation import scan_trend_pullbacks

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
CANDIDATES = [
    {"name": "tp_15min_ema9_21_vwap_novol_none_long", "ema_fast": 9, "ema_slow": 21, "require_vwap_alignment": True, "require_volume": False, "volume_min": 1.0, "gate": "none", "direction": "long"},
    {"name": "tp_15min_ema9_21_vwap_vol12_none_long", "ema_fast": 9, "ema_slow": 21, "require_vwap_alignment": True, "require_volume": True, "volume_min": 1.2, "gate": "none", "direction": "long"},
    {"name": "tp_15min_ema9_21_novwap_vol12_none_long", "ema_fast": 9, "ema_slow": 21, "require_vwap_alignment": False, "require_volume": True, "volume_min": 1.2, "gate": "none", "direction": "long"},
    {"name": "tp_15min_ema9_21_novwap_vol12_bull_long", "ema_fast": 9, "ema_slow": 21, "require_vwap_alignment": False, "require_volume": True, "volume_min": 1.2, "gate": "bull", "direction": "long"},
]


def scan_candidate(frame, candidate):
    events = scan_trend_pullbacks(
        frame,
        timeframe="15min",
        direction=candidate["direction"],
        ema_fast=candidate["ema_fast"],
        ema_slow=candidate["ema_slow"],
        atr_period=14,
        trend_slope_bars=3,
        impulse_lookback=5,
        pullback_lookback=3,
        impulse_atr=0.75,
        vwap_tolerance_atr=0.50,
        break_buffer_atr=0.05,
        stop_buffer_atr=0.10,
        reward_risk=2.0,
        volume_lookback=20,
        volume_min=1.0,
        require_volume=False,
        require_vwap_alignment=candidate["require_vwap_alignment"],
        allow_shorts=False,
        session_start="09:30",
        session_end="15:30",
        one_signal_per_session=True,
    )
    result = []
    for event in events:
        timestamp = pd.Timestamp(event["confirmation_timestamp"])
        if candidate["require_volume"] and (event.get("volume_ratio") is None or float(event["volume_ratio"]) < candidate["volume_min"]):
            continue
        result.append({**event, "break_timestamp": timestamp, "session_date": timestamp.tz_convert("America/New_York").strftime("%Y-%m-%d")})
    return result


def metric(curve):
    if curve.empty:
        return 0.0, 0.0
    return (float(curve.iloc[-1]) / START_CAPITAL - 1.0) * 100.0, float((curve / curve.cummax() - 1.0).min()) * 100.0


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    baseline_params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    symbols = [symbol for symbol in SYMBOLS if daily[symbol] is not None and fifteen[symbol] is not None]
    daily_frames = {symbol: daily[symbol] for symbol in symbols}
    frames = {symbol: fifteen[symbol] for symbol in symbols}
    dates = sorted({day for frame in frames.values() for day in frame["session_date"].unique()})
    regimes = build_regimes(daily_frames, symbols)
    prepared = {symbol: prepare_daybreakout(frames[symbol], baseline_params) for symbol in symbols}
    event_cache = {candidate["name"]: {symbol: scan_candidate(frames[symbol], candidate) for symbol in symbols} for candidate in CANDIDATES}
    fold_size = 20
    fold_count = min(5, len(dates) // fold_size)
    folds = {f"fold_{idx + 1}": dates[-fold_size * (idx + 1) : -fold_size * idx if idx else None] for idx in range(fold_count)}
    folds = dict(reversed(list(folds.items())))
    rows = []
    for fold_name, fold_dates in folds.items():
        baseline_curves = []
        for symbol in symbols:
            curve, _ = simulate_daybreakout(symbol, prepared[symbol], fold_dates, baseline_params, regimes, START_CAPITAL / len(symbols))
            if not curve.empty:
                baseline_curves.append(curve)
        baseline_return, baseline_dd = metric(aggregate_curves(baseline_curves))
        rows.append({"variant": "baseline_day_breakout_s78", "fold": fold_name, "return_pct": baseline_return, "max_drawdown_pct": baseline_dd, "delta_return_pp": 0.0, "delta_drawdown_pp": 0.0, "signals": 0})
        for candidate in CANDIDATES:
            curves = []
            signals = 0
            for symbol in symbols:
                events = [event for event in event_cache[candidate["name"]][symbol] if fold_dates[0] <= event["session_date"] <= fold_dates[-1] and gate_allows(event, candidate["gate"], regimes)]
                signals += len(events)
                curve, _ = simulate_vwap_fast(symbol, frames[symbol], events, fold_dates, START_CAPITAL / len(symbols), 20)
                if not curve.empty:
                    curves.append(curve)
            ret, dd = metric(aggregate_curves(curves))
            rows.append({"variant": candidate["name"], "fold": fold_name, "return_pct": ret, "max_drawdown_pct": dd, "delta_return_pp": ret - baseline_return, "delta_drawdown_pp": dd - baseline_dd, "signals": signals})
    output = OUT_DIR / "trend_pullback_walkforward_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    with open(OUT_DIR / "trend_pullback_walkforward_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump({"folds": folds, "candidates": CANDIDATES, "symbols": symbols, "output": str(output)}, handle, indent=2)
    print(pd.DataFrame(rows).to_string(index=False))


if __name__ == "__main__":
    main()
