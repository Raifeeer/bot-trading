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
from strategies.breakout_20_55_volume import scan_breakouts

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"


def build_variants() -> list[dict]:
    variants = []
    for timeframe in ("5min", "15min"):
        for lookback in (20, 55):
            for volume_min in (0.0, 1.0, 1.2):
                for gate in ("none", "bull"):
                    variants.append(
                        {
                            "name": f"breakout_{timeframe}_lb{lookback}_vol{str(volume_min).replace('.', '')}_{gate}",
                            "timeframe": timeframe,
                            "lookback": lookback,
                            "volume_min": volume_min,
                            "gate": gate,
                            "hold_max_bars": 36 if timeframe == "5min" else 20,
                        }
                    )
    return variants


def scan_events(frame: pd.DataFrame, variant: dict) -> list[dict]:
    events = scan_breakouts(
        frame,
        timeframe=variant["timeframe"],
        lookback=variant["lookback"],
        volume_lookback=20,
        volume_min=variant["volume_min"],
        atr_period=14,
        break_buffer_atr=0.0,
        stop_buffer_atr=0.10,
        reward_risk=1.5,
        hold_max_bars=variant["hold_max_bars"],
        session_start="09:30",
        session_end="15:30",
        one_signal_per_session=True,
        allow_shorts=False,
    )
    return [
        {
            **event,
            "break_timestamp": pd.Timestamp(event["confirmation_timestamp"]),
            "session_date": pd.Timestamp(event["confirmation_timestamp"]).tz_convert("America/New_York").strftime("%Y-%m-%d"),
        }
        for event in events
    ]


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
    prepared = {symbol: prepare_daybreakout(fifteen[symbol], baseline_params) for symbol in symbols}
    variants = build_variants()
    event_cache: dict[tuple, dict[str, list[dict]]] = {}
    for variant in variants:
        key = (variant["timeframe"], variant["lookback"], variant["volume_min"])
        if key not in event_cache:
            event_cache[key] = {symbol: scan_events(frames[variant["timeframe"]][symbol], variant) for symbol in symbols}

    rows: list[dict] = []
    trades_out: list[dict] = []
    for window_name, dates in windows["15min"].items():
        curves, trades = [], []
        for symbol in symbols:
            curve, symbol_trades = simulate_daybreakout(symbol, prepared[symbol], dates, baseline_params, regimes, START_CAPITAL / len(symbols))
            if not curve.empty:
                curves.append(curve)
            trades.extend(symbol_trades)
        rows.append(metric_row(aggregate_curves(curves), trades, "baseline_day_breakout_s78", "15min", window_name, 0))

    for variant in variants:
        timeframe = variant["timeframe"]
        key = (timeframe, variant["lookback"], variant["volume_min"])
        for window_name, dates in windows[timeframe].items():
            curves, trades = [], []
            signals = 0
            for symbol in symbols:
                events = [event for event in event_cache[key][symbol] if in_window(event["session_date"], dates) and gate_allows(event, variant["gate"], regimes)]
                signals += len(events)
                curve, symbol_trades = simulate_vwap_fast(symbol, frames[timeframe][symbol], events, dates, START_CAPITAL / len(symbols), variant["hold_max_bars"])
                if not curve.empty:
                    curves.append(curve)
                trades.extend(symbol_trades)
                trades_out.extend([{**trade, "variant": variant["name"], "window": window_name, "symbol": symbol} for trade in symbol_trades])
            rows.append(metric_row(aggregate_curves(curves), trades, variant["name"], timeframe, window_name, signals))

    result = OUT_DIR / "breakout_20_55_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(result, index=False)
    pd.DataFrame(trades_out).to_csv(OUT_DIR / "breakout_20_55_backtest_trades_2026-08-19.csv", index=False)
    manifest = {
        "source": "real Alpaca IEX 5m/15m caches plus daily setup_history",
        "symbols_used": symbols,
        "missing_symbols": missing,
        "variants": len(variants),
        "lookbacks": [20, 55],
        "volume_min": [0.0, 1.0, 1.2],
        "slippage_per_side": 0.0005,
        "session": "09:30-15:30 America/New_York; no overnight",
        "entry": "next bar open after prior-channel close breakout",
        "baseline": "DayBreakout current config + S78 regime bull gate",
        "anti_lookahead": ["channel excludes current bar", "volume baseline shifted", "entry next open", "daily regime prior data", "warmup excluded"],
        "outputs": [str(result), str(OUT_DIR / "breakout_20_55_backtest_trades_2026-08-19.csv")],
    }
    with open(OUT_DIR / "breakout_20_55_backtest_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(json.dumps({"rows": len(rows), "trades": len(trades_out), "variants": len(variants), "symbols": symbols}, indent=2))


if __name__ == "__main__":
    main()
