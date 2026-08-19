from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from risk.regime import apply_crash_cooldown, classify_regime
from scripts.run_orb_backtests import (
    DAILY_DIR,
    FIFTEEN_DIR,
    OUT_DIR,
    SLIPPAGE,
    START_CAPITAL,
    SYMBOLS,
    aggregate_curves,
    build_windows,
    date_key,
    load_pickle,
    metric_row,
    normalise,
    prepare_daybreakout,
)
from strategies.relative_strength_priority import evaluate_priority

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"


def previous_daily_frame(frame: pd.DataFrame, day: str) -> pd.DataFrame:
    day_ts = pd.Timestamp(day, tz="America/New_York").tz_convert("UTC")
    return frame.loc[frame.index < day_ts]


def build_regimes(daily: dict[str, pd.DataFrame], symbols: list[str]) -> dict[str, dict]:
    dates = sorted({date_key(index) for symbol in symbols for index in daily[symbol].index})
    states: dict[str, dict] = {}
    bot_state: dict = {}
    for day in dates:
        prior = {symbol: previous_daily_frame(daily[symbol], day) for symbol in symbols}
        states[day] = apply_crash_cooldown(classify_regime(prior, symbols), bot_state, pd.Timestamp(day).to_pydatetime())
    return states


def simulate_overlay(symbol: str, frame: pd.DataFrame, dates: list[str], params: dict, regimes: dict[str, dict], priority_by_day: dict[str, set[str]], initial_capital: float, gate: str) -> tuple[pd.Series, list[dict]]:
    start_ts = pd.Timestamp(dates[0], tz="America/New_York").tz_convert("UTC")
    end_ts = pd.Timestamp(dates[-1], tz="America/New_York").tz_convert("UTC") + pd.Timedelta(days=1)
    data = frame.loc[(frame.index >= start_ts - pd.Timedelta(days=10)) & (frame.index < end_ts)].copy()
    if len(data) < 80:
        return pd.Series(dtype=float), []
    session_start = params.get("session_start", "10:00")
    session_end = params.get("session_end", "15:30")
    hold_max = int(params.get("hold_max_bars", 20))
    cash = float(initial_capital)
    shares = 0.0
    entry_price = None
    stop_price = None
    bars_held = 0
    pending = None
    curve: dict[pd.Timestamp, float] = {}
    trades: list[dict] = []
    for idx in range(len(data)):
        row = data.iloc[idx]
        timestamp = data.index[idx]
        day = str(data["session_date"].iloc[idx])
        active = dates[0] <= day <= dates[-1]
        local_time = timestamp.tz_convert("America/New_York").strftime("%H:%M")
        if active and pending is not None and shares == 0.0 and cash > 0.0:
            fill = float(row["open"]) * (1.0 + SLIPPAGE)
            shares = cash / fill
            cash = 0.0
            entry_price = fill
            stop_price = pending["stop_price"]
            bars_held = 0
            pending = None
        if active and shares > 0.0:
            bars_held += 1
            stop_hit = float(row["low"]) <= float(stop_price or row["close"])
            fallback = pd.notna(row["donch_lo"]) and float(row["close"]) < float(row["donch_lo"])
            max_hold = bars_held >= hold_max
            if stop_hit or fallback or max_hold:
                reason = "stop" if stop_hit else ("reversión al canal" if fallback else "máximo de barras")
                exit_px = min(float(row["low"]), float(stop_price or row["close"])) if stop_hit else float(row["close"])
                exit_px *= 1.0 - SLIPPAGE
                pnl = shares * (exit_px - float(entry_price))
                cash = shares * exit_px
                trades.append({"symbol": symbol, "direction": "bull", "entry": float(entry_price), "exit": float(exit_px), "pnl": float(pnl), "reason": reason, "bars_held": bars_held, "session_date": day})
                shares = 0.0
                entry_price = None
                stop_price = None
                bars_held = 0
        elif active and session_start <= local_time < session_end and pd.notna(row["donch_hi"]):
            regime = regimes.get(day, {}).get("regime", "cash")
            allowed = gate == "none" or regime == "bull"
            breakout = float(row["close"]) > float(row["donch_hi"])
            prior_break = idx > 0 and pd.notna(data.iloc[idx - 1]["donch_hi"]) and float(data.iloc[idx - 1]["close"]) > float(data.iloc[idx - 1]["donch_hi"])
            if breakout and not prior_break and allowed and symbol in priority_by_day.get(day, set()):
                stop = float(row["close"]) - float(params["atr_multiplier_stop"]) * float(row["atr"])
                pending = {"stop_price": max(stop, 0.01)}
        if active:
            curve[timestamp] = cash + shares * float(row["close"])
    if shares > 0.0 and len(data):
        last = data.iloc[-1]
        exit_px = float(last["close"]) * (1.0 - SLIPPAGE)
        cash = shares * exit_px
        trades.append({"symbol": symbol, "direction": "bull", "entry": float(entry_price), "exit": float(exit_px), "pnl": float(shares * (exit_px - float(entry_price))), "reason": "end_of_window", "bars_held": bars_held, "session_date": str(data["session_date"].iloc[-1])})
        curve[data.index[-1]] = cash
    return pd.Series(curve).sort_index(), trades


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    symbols = [symbol for symbol in SYMBOLS if daily[symbol] is not None and fifteen[symbol] is not None]
    regimes = build_regimes({symbol: daily[symbol] for symbol in symbols}, symbols)
    frames = {symbol: fifteen[symbol] for symbol in symbols}
    windows = build_windows(frames, "15min")
    prepared = {symbol: prepare_daybreakout(fifteen[symbol], params) for symbol in symbols}
    variants = []
    for horizon in (20, 60):
        for top_k in (1, 2):
            for only_positive in (False, True):
                variants.append({"name": f"rs_priority_h{horizon}_k{top_k}_{'positive' if only_positive else 'relative'}", "horizon_bars": horizon, "top_k": top_k, "only_positive": only_positive, "gate": "bull"})
    all_days = sorted({str(day) for symbol in symbols for day in daily[symbol]["session_date"].unique()})
    snapshots: dict[tuple, set[str]] = {}
    for variant in variants:
        for day in all_days:
            prior = {symbol: previous_daily_frame(daily[symbol], day) for symbol in symbols}
            result = evaluate_priority(prior, horizon_bars=variant["horizon_bars"], top_k=variant["top_k"], gate="none", current_regime=regimes.get(day, {}).get("regime", "cash"), only_positive=variant["only_positive"])
            snapshots[(variant["name"], day)] = set(result.get("leader_symbols", []))
    rows = []
    trades_out = []
    for window_name, dates in windows.items():
        base_curves, base_trades = [], []
        for symbol in symbols:
            from scripts.run_orb_backtests import simulate_daybreakout
            curve, trades = simulate_daybreakout(symbol, prepared[symbol], dates, params, regimes, START_CAPITAL / len(symbols))
            if not curve.empty:
                base_curves.append(curve)
            base_trades.extend(trades)
        rows.append(metric_row(aggregate_curves(base_curves), base_trades, "baseline_day_breakout_s78", "15min", window_name, 0))
        for variant in variants:
            for gate in ("none", "bull"):
                name = f"{variant['name']}_{gate}"
                curves, trades = [], []
                eligible_days = dates
                for symbol in symbols:
                    priority = {day: snapshots.get((variant["name"], day), set()) for day in eligible_days}
                    curve, symbol_trades = simulate_overlay(symbol, prepared[symbol], dates, params, regimes, priority, START_CAPITAL / len(symbols), gate)
                    if not curve.empty:
                        curves.append(curve)
                    trades.extend(symbol_trades)
                    trades_out.extend([{**trade, "variant": name, "window": window_name} for trade in symbol_trades])
                rows.append(metric_row(aggregate_curves(curves), trades, name, "15min", window_name, len(trades)))
    result_path = OUT_DIR / "relative_strength_priority_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(result_path, index=False)
    pd.DataFrame(trades_out).to_csv(OUT_DIR / "relative_strength_priority_trades_2026-08-19.csv", index=False)
    with open(OUT_DIR / "relative_strength_priority_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump({"variants": len(variants) * 2, "symbols": symbols, "source": "real daily setup_history plus 15m intraday caches", "entry": "next open after existing DayBreakout signal", "cost_bps_per_side": 5.0, "output": str(result_path)}, handle, indent=2)
    print(json.dumps({"rows": len(rows), "trades": len(trades_out), "variants": len(variants) * 2, "symbols": symbols}, indent=2))


if __name__ == "__main__":
    main()
