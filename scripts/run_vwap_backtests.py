from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from scripts.run_orb_backtests import (
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
from strategies.vwap_reclaim_pullback import scan_vwap

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
DAILY_DIR = ROOT / "backtests/setup_history"
FIFTEEN_DIR = ROOT / "backtests/volume_profile_history"
FIVE_DIR = ROOT / "backtests/structure_mtf_history"
OUT_DIR = ROOT / "backtests"


def build_variants() -> list[dict]:
    variants = []
    for timeframe in ("5min", "15min"):
        for mode in ("reclaim", "pullback"):
            for direction in ("long", "short", "both"):
                for volume_label, require_volume, volume_min in (
                    ("novol", False, 1.0),
                    ("vol12", True, 1.2),
                ):
                    for gate in ("none", "directional"):
                        variants.append(
                            {
                                "name": f"vwap_{timeframe}_{mode}_{direction}_{volume_label}_{gate}",
                                "timeframe": timeframe,
                                "mode": mode,
                                "direction": direction,
                                "require_volume": require_volume,
                                "volume_min": volume_min,
                                "gate": gate,
                                "hold_max_bars": 36 if timeframe == "5min" else 20,
                            }
                        )
    return variants


def scan_events(frame: pd.DataFrame, variant: dict) -> list[dict]:
    events = scan_vwap(
        frame,
        timeframe=variant["timeframe"],
        mode=variant["mode"],
        direction=variant["direction"],
        session_start="09:30",
        session_end="15:30",
        atr_period=14,
        min_impulse_bars=2,
        displacement_atr=0.50,
        vwap_tolerance_atr=0.25,
        max_penetration_atr=0.75,
        break_buffer_atr=0.05,
        volume_lookback=20,
        volume_min=1.0,
        require_volume=False,
        pullback_lookback=3,
        stop_buffer_atr=0.10,
        reward_risk=2.0,
        one_signal_per_session=True,
    )
    return [
        {**event, "break_timestamp": pd.Timestamp(event["confirmation_timestamp"])}
        for event in events
    ]


def simulate_vwap_fast(
    symbol: str,
    frame: pd.DataFrame,
    events: list[dict],
    dates: list[str],
    initial_capital: float,
    hold_max_bars: int,
) -> tuple[pd.Series, list[dict]]:
    """Simular solo segmentos activos, conservando stops, targets y mark-to-market."""
    data = frame.loc[frame["session_date"].between(dates[0], dates[-1])].copy()
    if data.empty:
        return pd.Series(dtype=float), []
    timestamps = data.index
    index_by_timestamp = {int(timestamp.value): idx for idx, timestamp in enumerate(timestamps)}
    event_indices = sorted(
        (index_by_timestamp[int(pd.Timestamp(event["break_timestamp"]).value)], event)
        for event in events
        if int(pd.Timestamp(event["break_timestamp"]).value) in index_by_timestamp
    )
    opens = data["open"].to_numpy(dtype=float)
    highs = data["high"].to_numpy(dtype=float)
    lows = data["low"].to_numpy(dtype=float)
    closes = data["close"].to_numpy(dtype=float)
    equity = float(initial_capital)
    curve: dict[pd.Timestamp, float] = {timestamps[0]: equity, timestamps[-1]: equity}
    trades: list[dict] = []
    cursor = 0
    for event_idx, event in event_indices:
        entry_idx = event_idx + 1
        if entry_idx >= len(data) or entry_idx < cursor:
            continue
        side = event["direction"]
        entry_price = opens[entry_idx] * (1.0 + 0.0005 if side == "bull" else 1.0 - 0.0005)
        stop_price = float(event["stop_price"])
        target_price = float(event["target_price"])
        units = equity / max(entry_price, 1e-9)
        exit_idx = min(len(data) - 1, entry_idx + hold_max_bars - 1)
        reason = "end_of_window"
        exit_price = closes[exit_idx] * (1.0 - 0.0005 if side == "bull" else 1.0 + 0.0005)
        for idx in range(entry_idx, exit_idx + 1):
            if side == "bull" and lows[idx] <= stop_price:
                exit_idx = idx
                exit_price = min(lows[idx], stop_price) * (1.0 - 0.0005)
                reason = "stop"
                break
            if side == "bull" and highs[idx] >= target_price:
                exit_idx = idx
                exit_price = target_price * (1.0 - 0.0005)
                reason = "target"
                break
            if side == "bear" and highs[idx] >= stop_price:
                exit_idx = idx
                exit_price = max(highs[idx], stop_price) * (1.0 + 0.0005)
                reason = "stop"
                break
            if side == "bear" and lows[idx] <= target_price:
                exit_idx = idx
                exit_price = target_price * (1.0 + 0.0005)
                reason = "target"
                break
        for idx in range(entry_idx, exit_idx + 1):
            if side == "bull":
                curve[timestamps[idx]] = equity + units * (closes[idx] - entry_price)
            else:
                curve[timestamps[idx]] = equity + units * (entry_price - closes[idx])
        pnl = units * (exit_price - entry_price) if side == "bull" else units * (entry_price - exit_price)
        equity += pnl
        trades.append(
            {
                "symbol": symbol,
                "direction": side,
                "entry": round(entry_price, 8),
                "exit": round(exit_price, 8),
                "pnl": round(pnl, 8),
                "reason": reason,
                "bars_held": exit_idx - entry_idx + 1,
                "session_date": str(data["session_date"].iloc[exit_idx]),
            }
        )
        cursor = exit_idx + 1
        curve[timestamps[exit_idx]] = equity
    curve[timestamps[-1]] = equity
    return pd.Series(curve).sort_index(), trades


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    baseline_params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    five = {symbol: normalise(load_pickle(FIVE_DIR, symbol)) for symbol in SYMBOLS}
    missing = [
        symbol
        for symbol in SYMBOLS
        if daily[symbol] is None or fifteen[symbol] is None or five[symbol] is None
    ]
    symbols = [symbol for symbol in SYMBOLS if symbol not in missing]
    if len(symbols) < 5:
        raise RuntimeError(f"Cobertura insuficiente; faltan: {missing}")
    regimes = build_regimes({symbol: daily[symbol] for symbol in symbols}, symbols)
    frames = {
        "5min": {symbol: five[symbol] for symbol in symbols},
        "15min": {symbol: fifteen[symbol] for symbol in symbols},
    }
    windows_by_timeframe = {
        timeframe: build_windows(data, timeframe) for timeframe, data in frames.items()
    }
    prepared_fifteen = {
        symbol: prepare_daybreakout(fifteen[symbol], baseline_params) for symbol in symbols
    }
    variants = build_variants()
    event_cache: dict[tuple, dict[str, list[dict]]] = {}
    for variant in variants:
        key = (
            variant["timeframe"],
            variant["mode"],
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
    for window_name, dates in windows_by_timeframe["15min"].items():
        curves, trades = [], []
        for symbol in symbols:
            curve, symbol_trades = simulate_daybreakout(
                symbol,
                prepared_fifteen[symbol],
                dates,
                baseline_params,
                regimes,
                START_CAPITAL / len(symbols),
            )
            if not curve.empty:
                curves.append(curve)
            trades.extend(symbol_trades)
        baseline_cache[window_name] = {"curve": aggregate_curves(curves), "trades": trades}
        rows.append(metric_row(baseline_cache[window_name]["curve"], trades, "baseline_day_breakout_s78", "15min", window_name, 0))

    for variant in variants:
        timeframe = variant["timeframe"]
        cache_key = (
            timeframe,
            variant["mode"],
            variant["direction"],
        )
        for window_name, dates in windows_by_timeframe[timeframe].items():
            curves, trades = [], []
            events_count = 0
            for symbol in symbols:
                all_events = event_cache[cache_key][symbol]
                window_events = [
                    event
                    for event in all_events
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
                events_count += len(window_events)
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
                trade_rows.extend(
                    [
                        {
                            **trade,
                            "variant": variant["name"],
                            "window": window_name,
                        }
                        for trade in symbol_trades
                    ]
                )
            rows.append(
                metric_row(
                    aggregate_curves(curves),
                    trades,
                    variant["name"],
                    timeframe,
                    window_name,
                    events_count,
                )
            )

    output = OUT_DIR / "vwap_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    pd.DataFrame(trade_rows).to_csv(OUT_DIR / "vwap_backtest_trades_2026-08-19.csv", index=False)
    manifest = {
        "date": "2026-08-19",
        "strategy": "VWAP reclaim/pullback",
        "symbols_requested": SYMBOLS,
        "symbols_used": symbols,
        "missing_symbols": missing,
        "timeframes": {key: sorted(value) for key, value in windows_by_timeframe.items()},
        "variants": len(variants),
        "slippage_per_side": 0.0005,
        "session": "09:30-15:30 America/New_York; RTH VWAP reset each local session",
        "entry": "next bar open after closed confirmation",
        "overnight": False,
        "shorts": "research-only; gate directional uses bear/crash regime",
        "baseline": "DayBreakout S78 exact params from config/config.yaml",
        "anti_lookahead": [
            "VWAP uses only closed bars up to confirmation",
            "volume reference is shifted and rolling",
            "daily regime uses previous daily bars",
            "baseline receives warmup history but metrics stay inside each window",
        ],
        "outputs": [
            str(output),
            str(OUT_DIR / "vwap_backtest_trades_2026-08-19.csv"),
        ],
    }
    with open(OUT_DIR / "vwap_backtest_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(json.dumps({"rows": len(rows), "trades": len(trade_rows), "symbols": symbols}, indent=2))


if __name__ == "__main__":
    main()
