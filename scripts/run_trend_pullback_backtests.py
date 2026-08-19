from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from scripts.run_orb_backtests import (
    DAILY_DIR,
    FIFTEEN_DIR,
    FIVE_DIR,
    OUT_DIR,
    START_CAPITAL,
    SYMBOLS,
    aggregate_curves,
    build_regimes,
    build_windows,
    gate_allows,
    in_window,
    load_pickle,
    metric_row,
    normalise,
    prepare_daybreakout,
    simulate_daybreakout,
)
from scripts.run_vwap_backtests import simulate_vwap_fast
from strategies.trend_pullback_continuation import scan_trend_pullbacks

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"


def build_variants() -> list[dict]:
    variants = []
    for timeframe in ("5min", "15min"):
        for profile, fast, slow in (("ema9_21", 9, 21), ("ema12_26", 12, 26), ("ema20_50", 20, 50)):
            for align_label, require_vwap in (("novwap", False), ("vwap", True)):
                for volume_label, require_volume, volume_min in (("novol", False, 1.0), ("vol12", True, 1.2)):
                    for gate in ("none", "bull", "directional"):
                        for direction in ("long", "both"):
                            variants.append(
                                {
                                    "name": f"tp_{timeframe}_{profile}_{align_label}_{volume_label}_{gate}_{direction}",
                                    "timeframe": timeframe,
                                    "profile": profile,
                                    "ema_fast": fast,
                                    "ema_slow": slow,
                                    "require_vwap_alignment": require_vwap,
                                    "require_volume": require_volume,
                                    "volume_min": volume_min,
                                    "gate": gate,
                                    "direction": direction,
                                    "allow_shorts": direction == "both",
                                    "hold_max_bars": 36 if timeframe == "5min" else 20,
                                }
                            )
    return variants


def scan_events(frame: pd.DataFrame, variant: dict) -> list[dict]:
    events = scan_trend_pullbacks(
        frame,
        timeframe=variant["timeframe"],
        direction=variant["direction"],
        ema_fast=variant["ema_fast"],
        ema_slow=variant["ema_slow"],
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
        require_vwap_alignment=variant["require_vwap_alignment"],
        allow_shorts=variant["allow_shorts"],
        session_start="09:30",
        session_end="15:30",
        one_signal_per_session=True,
    )
    output = []
    for event in events:
        timestamp = pd.Timestamp(event["confirmation_timestamp"])
        output.append(
            {
                **event,
                "break_timestamp": timestamp,
                "session_date": timestamp.tz_convert("America/New_York").strftime("%Y-%m-%d"),
            }
        )
    return output


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    baseline_params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    five = {symbol: normalise(load_pickle(FIVE_DIR, symbol)) for symbol in SYMBOLS}
    missing = [symbol for symbol in SYMBOLS if daily[symbol] is None or fifteen[symbol] is None or five[symbol] is None]
    symbols = [symbol for symbol in SYMBOLS if symbol not in missing]
    if len(symbols) < 5:
        raise RuntimeError(f"Cobertura insuficiente; faltan: {missing}")
    regimes = build_regimes({symbol: daily[symbol] for symbol in symbols}, symbols)
    frames = {"5min": {symbol: five[symbol] for symbol in symbols}, "15min": {symbol: fifteen[symbol] for symbol in symbols}}
    windows = {timeframe: build_windows(data, timeframe) for timeframe, data in frames.items()}
    prepared_fifteen = {symbol: prepare_daybreakout(fifteen[symbol], baseline_params) for symbol in symbols}
    variants = build_variants()
    event_cache: dict[tuple, dict[str, list[dict]]] = {}
    for variant in variants:
        key = (
            variant["timeframe"],
            variant["profile"],
            variant["require_vwap_alignment"],
            variant["direction"],
        )
        if key in event_cache:
            continue
        event_cache[key] = {}
        for symbol in symbols:
            event_cache[key][symbol] = scan_events(frames[variant["timeframe"]][symbol], variant)

    rows: list[dict] = []
    trade_rows: list[dict] = []
    baseline_cache: dict[str, dict] = {}
    for window_name, dates in windows["15min"].items():
        curves, trades = [], []
        for symbol in symbols:
            curve, symbol_trades = simulate_daybreakout(symbol, prepared_fifteen[symbol], dates, baseline_params, regimes, START_CAPITAL / len(symbols))
            if not curve.empty:
                curves.append(curve)
            trades.extend(symbol_trades)
        baseline_cache[window_name] = {"curve": aggregate_curves(curves), "trades": trades}
        rows.append(metric_row(baseline_cache[window_name]["curve"], baseline_cache[window_name]["trades"], "baseline_day_breakout_s78", "15min", window_name, 0))

    for variant in variants:
        timeframe = variant["timeframe"]
        cache_key = (
            timeframe,
            variant["profile"],
            variant["require_vwap_alignment"],
            variant["direction"],
        )
        for window_name, dates in windows[timeframe].items():
            curves, trades = [], []
            signals = 0
            for symbol in symbols:
                all_events = event_cache[cache_key][symbol]
                window_events = [
                    event for event in all_events
                    if in_window(event["session_date"], dates)
                    and gate_allows(event, variant["gate"], regimes)
                    and (
                        not variant["require_volume"]
                        or (
                            event.get("volume_ratio") is not None
                            and float(event["volume_ratio"]) >= variant["volume_min"]
                        )
                    )
                ]
                signals += len(window_events)
                curve, symbol_trades = simulate_vwap_fast(
                    symbol,
                    frames[timeframe][symbol],
                    window_events,
                    dates,
                    START_CAPITAL / len(symbols),
                    variant["hold_max_bars"],
                )
                if not curve.empty:
                    curves.append(curve)
                trades.extend(symbol_trades)
                trade_rows.extend([{**trade, "variant": variant["name"], "window": window_name} for trade in symbol_trades])
            rows.append(metric_row(aggregate_curves(curves), trades, variant["name"], timeframe, window_name, signals))

    output = OUT_DIR / "trend_pullback_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    pd.DataFrame(trade_rows).to_csv(OUT_DIR / "trend_pullback_backtest_trades_2026-08-19.csv", index=False)
    manifest = {
        "date": "2026-08-19",
        "strategy": "EMA/VWAP trend pullback continuation",
        "symbols_requested": SYMBOLS,
        "symbols_used": symbols,
        "missing_symbols": missing,
        "timeframes": {key: sorted(value) for key, value in windows.items()},
        "variants": len(variants),
        "slippage_per_side": 0.0005,
        "session": "09:30-15:30 America/New_York; no overnight",
        "entry": "next bar open after closed confirmation",
        "baseline": "DayBreakout S78 exact params from config/config.yaml",
        "bearish": "direction=both is research-only; RiskManager policy remains unchanged",
        "anti_lookahead": [
            "EMA/ATR/VWAP/volume use data through confirmation bar",
            "entry is next bar open",
            "daily regime uses previous daily data",
            "baseline receives warmup history but metrics stay inside each window",
        ],
        "outputs": [str(output), str(OUT_DIR / "trend_pullback_backtest_trades_2026-08-19.csv")],
    }
    with open(OUT_DIR / "trend_pullback_backtest_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(json.dumps({"rows": len(rows), "trades": len(trade_rows), "variants": len(variants), "symbols": symbols}, indent=2))


if __name__ == "__main__":
    main()
