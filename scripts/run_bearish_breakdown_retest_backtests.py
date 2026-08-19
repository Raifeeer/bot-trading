"""Backtest de breakdown/retest bearish sobre subyacente, sin P&L de opciones."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from risk.regime import apply_crash_cooldown, classify_regime
from scripts.run_structure_mtf_backtests import (
    date_key,
    load_pickle,
    normalise,
    previous_daily_frame,
)
from strategies.bearish_breakdown_retest import scan_breakdown_retests

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
OUT = ROOT / "backtests"
DAILY_DIR = ROOT / "backtests/setup_history"
FIFTEEN_DIR = ROOT / "backtests/volume_profile_history"
FIVE_DIR = ROOT / "backtests/structure_mtf_history"
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
START_CAPITAL = 100_000.0
SLIPPAGE = 0.0005
RISK_PER_TRADE = 0.005


def rth(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    out = normalise(frame)
    if out is None:
        return None
    local = out.index.tz_convert("America/New_York")
    mask = (local.time >= pd.Timestamp("09:30").time()) & (local.time < pd.Timestamp("16:00").time())
    return out.loc[mask]


def build_regimes(daily: dict[str, pd.DataFrame], symbols: list[str]) -> dict[str, dict]:
    dates = sorted({date_key(index) for symbol in symbols for index in daily[symbol].index})
    states: dict[str, dict] = {}
    bot_state: dict[str, Any] = {}
    for day in dates:
        prior = {symbol: previous_daily_frame(daily[symbol], day) for symbol in symbols}
        state = classify_regime(prior, symbols)
        states[day] = apply_crash_cooldown(state, bot_state, pd.Timestamp(day).to_pydatetime())
    return states


def event_day(ts: pd.Timestamp) -> str:
    return date_key(ts)


def variants() -> list[dict[str, Any]]:
    return [
        {"name": "br15_lb10_v12_rt3", "timeframe": "15min", "lookback": 10, "volume_min": 1.2, "retest_max_bars": 3},
        {"name": "br15_lb20_v12_rt3", "timeframe": "15min", "lookback": 20, "volume_min": 1.2, "retest_max_bars": 3},
        {"name": "br15_lb10_v10_rt2", "timeframe": "15min", "lookback": 10, "volume_min": 1.0, "retest_max_bars": 2},
        {"name": "br15_lb20_v10_rt3", "timeframe": "15min", "lookback": 20, "volume_min": 1.0, "retest_max_bars": 3},
        {"name": "br5_lb10_v12_rt3", "timeframe": "5min", "lookback": 10, "volume_min": 1.2, "retest_max_bars": 3},
        {"name": "br5_lb20_v12_rt3", "timeframe": "5min", "lookback": 20, "volume_min": 1.2, "retest_max_bars": 3},
        {"name": "br5_lb10_v10_rt2", "timeframe": "5min", "lookback": 10, "volume_min": 1.0, "retest_max_bars": 2},
        {"name": "br5_lb20_v10_rt3", "timeframe": "5min", "lookback": 20, "volume_min": 1.0, "retest_max_bars": 3},
    ]


def window_map(frames: dict[str, pd.DataFrame], n_days: int = 60) -> dict[str, list[str]]:
    dates = sorted({event_day(idx) for frame in frames.values() for idx in frame.index})
    recent = dates[-n_days:]
    return {
        "recent_5d": recent[-5:],
        "prior_5d": recent[-10:-5],
        "recent_20d": recent[-20:],
        "prior_20d": recent[-40:-20],
        "recent_60d": recent,
    }


def simulate_events(
    frame: pd.DataFrame,
    signals: list[dict[str, Any]],
    allowed_days: set[str],
    regime: dict[str, dict],
    gated: bool,
) -> tuple[list[dict[str, Any]], pd.Series]:
    signal_by_ts = {pd.Timestamp(item["confirmation_timestamp"]): item for item in signals}
    cash = START_CAPITAL
    position: dict[str, float] | None = None
    events: list[dict[str, Any]] = []
    curve: dict[pd.Timestamp, float] = {}
    last_trade_day: str | None = None
    for i, (ts, row) in enumerate(frame.iterrows()):
        day = event_day(ts)
        if position is not None:
            stop = position["stop"]
            target = position["target"]
            high = float(row["high"])
            low = float(row["low"])
            exit_price = None
            reason = None
            if high >= stop:
                exit_price, reason = stop * (1.0 + SLIPPAGE), "stop"
            elif low <= target:
                exit_price, reason = target * (1.0 + SLIPPAGE), "target"
            elif day != position["entry_day"]:
                exit_price, reason = float(row["open"]) * (1.0 + SLIPPAGE), "session_boundary"
            if exit_price is not None:
                pnl = position["shares"] * (position["entry"] - exit_price)
                cash += pnl
                events.append({**position, "exit": exit_price, "pnl": pnl, "r_multiple": pnl / position["risk_dollars"], "reason": reason})
                position = None
        if position is None and ts in signal_by_ts and day in allowed_days and day != last_trade_day:
            if gated:
                state = regime.get(day, {})
                if state.get("regime") not in {"bear", "crash"}:
                    curve[ts] = cash
                    continue
            signal = signal_by_ts[ts]
            if i + 1 >= len(frame):
                continue
            next_ts = frame.index[i + 1]
            if event_day(next_ts) != day:
                continue
            entry = float(frame.iloc[i + 1]["open"]) * (1.0 - SLIPPAGE)
            stop = float(signal["stop_price"])
            target = float(signal["target_price"])
            risk_per_share = max(stop - entry, entry * 0.001)
            risk_dollars = START_CAPITAL * RISK_PER_TRADE
            shares = risk_dollars / risk_per_share
            position = {
                "entry_timestamp": next_ts,
                "entry_day": day,
                "entry": entry,
                "stop": stop,
                "target": target,
                "shares": shares,
                "risk_dollars": risk_dollars,
                "break_timestamp": signal["break_timestamp"],
                "confirmation_timestamp": signal["confirmation_timestamp"],
                "support_level": signal["support_level"],
            }
            last_trade_day = day
        mark = cash
        if position is not None:
            mark += position["shares"] * (position["entry"] - float(row["close"]))
        curve[ts] = mark
    if position is not None and len(frame):
        last = frame.iloc[-1]
        exit_price = float(last["close"]) * (1.0 + SLIPPAGE)
        pnl = position["shares"] * (position["entry"] - exit_price)
        cash += pnl
        events.append({**position, "exit": exit_price, "pnl": pnl, "r_multiple": pnl / position["risk_dollars"], "reason": "end_of_window"})
        curve[frame.index[-1]] = cash
    return events, pd.Series(curve).sort_index()


def metrics(events: list[dict[str, Any]], curve: pd.Series, variant: str, window: str, gated: bool) -> dict[str, Any]:
    if curve.empty:
        return {"variant": variant, "window": window, "gated": gated, "return_pct": None, "max_drawdown_pct": None, "trades": 0, "win_rate_pct": None, "profit_factor": None, "avg_r": None}
    peak = curve.cummax()
    dd = curve / peak - 1.0
    wins = [float(item["pnl"]) for item in events if item["pnl"] > 0]
    losses = [abs(float(item["pnl"])) for item in events if item["pnl"] < 0]
    gross_loss = sum(losses)
    return {
        "variant": variant,
        "window": window,
        "gated": gated,
        "return_pct": round((float(curve.iloc[-1]) / START_CAPITAL - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(float(dd.min()) * 100.0, 6),
        "trades": len(events),
        "win_rate_pct": round(100.0 * len(wins) / len(events), 6) if events else None,
        "profit_factor": round(sum(wins) / gross_loss, 6) if gross_loss else None,
        "avg_r": round(sum(float(item["r_multiple"]) for item in events) / len(events), 6) if events else None,
        "signals_confirmed": len(events),
    }


def main() -> None:
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: rth(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    five = {symbol: rth(load_pickle(FIVE_DIR, symbol)) for symbol in SYMBOLS}
    available = [symbol for symbol in SYMBOLS if daily[symbol] is not None and fifteen[symbol] is not None and five[symbol] is not None]
    missing = [symbol for symbol in SYMBOLS if symbol not in available]
    regimes = build_regimes({symbol: daily[symbol] for symbol in available}, available)
    frames = {symbol: fifteen[symbol] for symbol in available}
    windows = window_map(frames, n_days=60)
    rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    for params in variants():
        source = five if params["timeframe"] == "5min" else fifteen
        for symbol in available:
            signals = scan_breakdown_retests(source[symbol], timeframe=params["timeframe"], lookback=params["lookback"], volume_min=params["volume_min"], retest_max_bars=params["retest_max_bars"])
            for signal in signals:
                event_rows.append({"variant": params["name"], "symbol": symbol, **signal})
            for window, days in windows.items():
                for gated in (False, True):
                    day_set = set(days)
                    window_frame = source[symbol].loc[
                        source[symbol].index.map(event_day).isin(day_set)
                    ]
                    selected = [signal for signal in signals if event_day(pd.Timestamp(signal["confirmation_timestamp"])) in day_set]
                    events, curve = simulate_events(window_frame, selected, day_set, regimes, gated)
                    metric_row = metrics(events, curve, params["name"], window, gated)
                    metric_row["symbol"] = symbol
                    rows.append(metric_row)
    OUT.mkdir(parents=True, exist_ok=True)
    result_path = OUT / "bearish_breakdown_retest_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(result_path, index=False)
    pd.DataFrame(event_rows).to_csv(OUT / "bearish_breakdown_retest_events_2026-08-19.csv", index=False)
    manifest = {
        "source": "real Alpaca IEX 5m/15m OHLCV caches",
        "symbols": available,
        "missing_symbols": missing,
        "variants": variants(),
        "windows": {key: [value[0], value[-1], len(value)] for key, value in windows.items()},
        "risk_per_trade_pct": RISK_PER_TRADE * 100.0,
        "slippage_bps": SLIPPAGE * 10000.0,
        "options_pnl": False,
        "lookahead": "support uses prior bars; entries next bar open; no overnight positions; RTH only",
        "regime_gate": "bear or crash for gated rows",
        "output": str(result_path),
    }
    with open(OUT / "bearish_breakdown_retest_backtests_2026-08-19_manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(result_path)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
