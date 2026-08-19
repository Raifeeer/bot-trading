"""Backtest reproducible de Opening Range Breakout frente a DayBreakout."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import ta
import yaml

from risk.regime import apply_crash_cooldown, classify_regime
from strategies.opening_range_breakout import scan_orb

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
DAILY_DIR = ROOT / "backtests/setup_history"
FIFTEEN_DIR = ROOT / "backtests/volume_profile_history"
FIVE_DIR = ROOT / "backtests/structure_mtf_history"
OUT_DIR = ROOT / "backtests"
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
START_CAPITAL = 100_000.0
SLIPPAGE = 0.0005


def load_pickle(directory: Path, symbol: str) -> pd.DataFrame | None:
    path = directory / f"{symbol}.pkl"
    if not path.exists():
        return None
    frame = pd.read_pickle(path)
    frame.index = pd.to_datetime(frame.index, utc=True)
    return frame.sort_index()


def normalise(frame: pd.DataFrame | None) -> pd.DataFrame | None:
    if frame is None or frame.empty:
        return None
    out = frame.copy()
    out.columns = [str(column).lower() for column in out.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(out.columns):
        return None
    out = out.dropna(subset=["open", "high", "low", "close", "volume"])
    out["session_date"] = out.index.tz_convert("America/New_York").strftime("%Y-%m-%d")
    return out


def date_key(value) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.tz_convert("America/New_York").strftime("%Y-%m-%d")


def previous_daily_frame(frame: pd.DataFrame, day: str) -> pd.DataFrame:
    day_ts = pd.Timestamp(day, tz="America/New_York").tz_convert("UTC")
    return frame.loc[frame.index < day_ts]


def build_regimes(daily: dict[str, pd.DataFrame], symbols: list[str]) -> dict[str, dict]:
    dates = sorted(
        {
            date_key(index)
            for symbol in symbols
            for index in daily[symbol].index
        }
    )
    states: dict[str, dict] = {}
    bot_state: dict = {}
    for day in dates:
        prior = {symbol: previous_daily_frame(daily[symbol], day) for symbol in symbols}
        regime = classify_regime(prior, symbols)
        states[day] = apply_crash_cooldown(
            regime, bot_state, pd.Timestamp(day).to_pydatetime()
        )
    return states


def build_windows(frames: dict[str, pd.DataFrame], timeframe: str) -> dict[str, list[str]]:
    dates = sorted({str(day) for frame in frames.values() for day in frame["session_date"].unique()})
    if len(dates) < 20:
        raise RuntimeError(f"Cobertura insuficiente para ORB {timeframe}: {len(dates)} días")
    windows = {
        "recent_5d": dates[-5:],
        "prior_5d": dates[-10:-5],
        "prior_10d": dates[-20:-10],
        "recent_20d": dates[-20:],
        "full_available": dates,
    }
    if len(dates) >= 40:
        windows["recent_40d"] = dates[-40:]
    return windows


def in_window(day: str, dates: list[str]) -> bool:
    return dates[0] <= day <= dates[-1]


def gate_allows(event: dict, gate: str, regimes: dict[str, dict]) -> bool:
    if gate == "none":
        return True
    state = regimes.get(event["session_date"], {})
    regime = state.get("regime", "cash")
    if gate == "bull":
        return event["direction"] == "bull" and regime == "bull"
    if gate == "bear_crash":
        return event["direction"] == "bear" and regime in {"bear", "crash"}
    if gate == "directional":
        return (
            event["direction"] == "bull" and regime == "bull"
        ) or (
            event["direction"] == "bear" and regime in {"bear", "crash"}
        )
    raise ValueError(f"Gate desconocido: {gate}")


def simulate_orb_symbol(
    symbol: str,
    frame: pd.DataFrame,
    events: list[dict],
    dates: list[str],
    gate: str,
    regimes: dict[str, dict],
    initial_capital: float,
    hold_max_bars: int,
) -> tuple[pd.Series, list[dict]]:
    data = frame.loc[frame["session_date"].between(dates[0], dates[-1])].copy()
    if data.empty:
        return pd.Series(dtype=float), []
    by_timestamp = {pd.Timestamp(event["break_timestamp"]): event for event in events}
    pending: dict | None = None
    side: str | None = None
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    bars_held = 0
    equity = float(initial_capital)
    units = 0.0
    realized = 0.0
    curve: dict[pd.Timestamp, float] = {}
    trades: list[dict] = []
    for idx in range(len(data)):
        timestamp = data.index[idx]
        session_day = str(data["session_date"].iloc[idx])
        row = data.iloc[idx]
        if pending is not None and side is None:
            raw_open = float(row["open"])
            side = pending["direction"]
            entry_price = raw_open * (1.0 + SLIPPAGE if side == "bull" else 1.0 - SLIPPAGE)
            stop_price = float(pending["stop_price"])
            target_price = float(pending["target_price"])
            units = equity / entry_price
            bars_held = 0
            pending = None
        if side is not None and entry_price is not None:
            bars_held += 1
            exit_price = None
            reason = None
            if side == "bull":
                if float(row["low"]) <= float(stop_price):
                    exit_price = min(float(row["low"]), float(stop_price)) * (1.0 - SLIPPAGE)
                    reason = "stop"
                elif float(row["high"]) >= float(target_price):
                    exit_price = float(target_price) * (1.0 - SLIPPAGE)
                    reason = "target"
            else:
                if float(row["high"]) >= float(stop_price):
                    exit_price = max(float(row["high"]), float(stop_price)) * (1.0 + SLIPPAGE)
                    reason = "stop"
                elif float(row["low"]) <= float(target_price):
                    exit_price = float(target_price) * (1.0 + SLIPPAGE)
                    reason = "target"
            if exit_price is None and bars_held >= hold_max_bars:
                exit_price = float(row["close"]) * (1.0 - SLIPPAGE if side == "bull" else 1.0 + SLIPPAGE)
                reason = "max_hold"
            if exit_price is not None:
                pnl = units * (exit_price - entry_price) if side == "bull" else units * (entry_price - exit_price)
                realized += pnl
                equity += pnl
                trades.append(
                    {
                        "symbol": symbol,
                        "direction": side,
                        "entry": round(entry_price, 8),
                        "exit": round(exit_price, 8),
                        "pnl": round(pnl, 8),
                        "reason": reason,
                        "bars_held": bars_held,
                        "session_date": session_day,
                    }
                )
                side = None
                entry_price = None
                stop_price = None
                target_price = None
                units = 0.0
                bars_held = 0
        if side is None:
            event = by_timestamp.get(timestamp)
            if event is not None and gate_allows(event, gate, regimes):
                pending = event
        if side == "bull" and entry_price is not None:
            mark = equity + units * (float(row["close"]) - entry_price)
        elif side == "bear" and entry_price is not None:
            mark = equity + units * (entry_price - float(row["close"]))
        else:
            mark = equity
        curve[timestamp] = mark
    if side is not None and entry_price is not None and len(data):
        row = data.iloc[-1]
        exit_price = float(row["close"]) * (1.0 - SLIPPAGE if side == "bull" else 1.0 + SLIPPAGE)
        pnl = units * (exit_price - entry_price) if side == "bull" else units * (entry_price - exit_price)
        equity += pnl
        trades.append(
            {
                "symbol": symbol,
                "direction": side,
                "entry": round(entry_price, 8),
                "exit": round(exit_price, 8),
                "pnl": round(pnl, 8),
                "reason": "end_of_window",
                "bars_held": bars_held,
                "session_date": str(data["session_date"].iloc[-1]),
            }
        )
        curve[data.index[-1]] = equity
    return pd.Series(curve).sort_index(), trades


def prepare_daybreakout(frame: pd.DataFrame, params: dict) -> pd.DataFrame:
    """Precalcular indicadores del baseline una sola vez por símbolo."""
    out = frame.copy()
    period = int(params["donchian_period"])
    atr_period = int(params["atr_period"])
    out["donch_hi"] = out["high"].shift(1).rolling(period).max()
    out["donch_lo"] = out["low"].shift(1).rolling(period).min()
    out["atr"] = ta.volatility.AverageTrueRange(
        out["high"], out["low"], out["close"], atr_period
    ).average_true_range()
    return out


def simulate_daybreakout(
    symbol: str,
    frame: pd.DataFrame,
    dates: list[str],
    params: dict,
    regimes: dict[str, dict],
    initial_capital: float,
) -> tuple[pd.Series, list[dict]]:
    start_ts = pd.Timestamp(dates[0], tz="America/New_York").tz_convert("UTC")
    end_ts = (
        pd.Timestamp(dates[-1], tz="America/New_York").tz_convert("UTC")
        + pd.Timedelta(days=1)
    )
    warmup_start = start_ts - pd.Timedelta(days=10)
    data = frame.loc[(frame.index >= warmup_start) & (frame.index < end_ts)].copy()
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
        session_day = str(data["session_date"].iloc[idx])
        active = in_window(session_day, dates)
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
                if stop_hit:
                    reason = "stop"
                    exit_px = min(float(row["low"]), float(stop_price or row["close"]))
                else:
                    reason = "reversión al canal" if fallback else "máximo de barras"
                    exit_px = float(row["close"])
                exit_px *= 1.0 - SLIPPAGE
                pnl = shares * (exit_px - float(entry_price))
                cash = shares * exit_px
                trades.append(
                    {
                        "symbol": symbol,
                        "direction": "bull",
                        "entry": round(float(entry_price), 8),
                        "exit": round(exit_px, 8),
                        "pnl": round(pnl, 8),
                        "reason": reason,
                        "bars_held": bars_held,
                        "session_date": session_day,
                    }
                )
                shares = 0.0
                entry_price = None
                stop_price = None
                bars_held = 0
        elif active and session_start <= local_time < session_end and pd.notna(row["donch_hi"]):
            breakout = float(row["close"]) > float(row["donch_hi"])
            prior_break = idx > 0 and pd.notna(data.iloc[idx - 1]["donch_hi"]) and float(data.iloc[idx - 1]["close"]) > float(data.iloc[idx - 1]["donch_hi"])
            regime = regimes.get(session_day, {}).get("regime", "cash")
            if breakout and not prior_break and regime == "bull":
                stop = float(row["close"]) - float(params["atr_multiplier_stop"]) * float(row["atr"])
                pending = {"stop_price": max(stop, 0.01)}
        if active:
            curve[timestamp] = cash + shares * float(row["close"])
    if shares > 0.0 and len(data):
        last = data.iloc[-1]
        exit_px = float(last["close"]) * (1.0 - SLIPPAGE)
        pnl = shares * (exit_px - float(entry_price))
        cash = shares * exit_px
        trades.append(
            {
                "symbol": symbol,
                "direction": "bull",
                "entry": round(float(entry_price), 8),
                "exit": round(exit_px, 8),
                "pnl": round(pnl, 8),
                "reason": "end_of_window",
                "bars_held": bars_held,
                "session_date": date_key(data.index[-1]),
            }
        )
        curve[data.index[-1]] = cash
    return pd.Series(curve).sort_index(), trades


def metric_row(
    curve: pd.Series,
    trades: list[dict],
    variant: str,
    timeframe: str,
    window: str,
    signals: int,
) -> dict:
    if curve.empty:
        return {
            "variant": variant,
            "timeframe": timeframe,
            "window": window,
            "return_pct": None,
            "max_drawdown_pct": None,
            "trades": 0,
            "signals": signals,
            "win_rate_pct": None,
            "profit_factor": None,
            "final_equity": None,
            "long_trades": 0,
            "short_trades": 0,
        }
    curve = curve.groupby(level=0).last()
    peak = curve.cummax()
    drawdown = curve / peak - 1.0
    wins = [float(trade["pnl"]) for trade in trades if trade["pnl"] > 0]
    losses = [abs(float(trade["pnl"])) for trade in trades if trade["pnl"] < 0]
    return {
        "variant": variant,
        "timeframe": timeframe,
        "window": window,
        "return_pct": round((float(curve.iloc[-1]) / START_CAPITAL - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(float(drawdown.min()) * 100.0, 6),
        "trades": len(trades),
        "signals": signals,
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 6) if trades else None,
        "profit_factor": round(sum(wins) / sum(losses), 6) if losses else None,
        "final_equity": round(float(curve.iloc[-1]), 6),
        "long_trades": sum(trade["direction"] == "bull" for trade in trades),
        "short_trades": sum(trade["direction"] == "bear" for trade in trades),
    }


def aggregate_curves(curves: list[pd.Series]) -> pd.Series:
    if not curves:
        return pd.Series(dtype=float)
    return pd.concat(curves, axis=1).ffill().fillna(START_CAPITAL / len(curves)).sum(axis=1)


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
    frames = {"5min": {symbol: five[symbol] for symbol in symbols}, "15min": {symbol: fifteen[symbol] for symbol in symbols}}
    prepared_fifteen = {symbol: prepare_daybreakout(fifteen[symbol], baseline_params) for symbol in symbols}
    windows_by_timeframe = {timeframe: build_windows(data, timeframe) for timeframe, data in frames.items()}
    variants = []
    for timeframe, ranges in (("5min", [5, 15, 30]), ("15min", [15, 30])):
        for opening_range in ranges:
            for direction in ("long", "short", "both"):
                for volume_label, require_volume, volume_min in (
                    ("novol", False, 1.0),
                    ("vol12", True, 1.2),
                ):
                    for gate in ("none", "directional"):
                        variants.append(
                            {
                                "name": f"orb_{timeframe}_r{opening_range}_{direction}_{volume_label}_{gate}",
                                "timeframe": timeframe,
                                "opening_range_minutes": opening_range,
                                "direction": direction,
                                "require_volume": require_volume,
                                "volume_min": volume_min,
                                "gate": gate,
                                "hold_max_bars": 20 if timeframe == "15min" else 36,
                            }
                        )
    event_cache: dict[tuple, dict[str, list[dict]]] = {}
    for variant in variants:
        key = (
            variant["timeframe"],
            variant["opening_range_minutes"],
            variant["direction"],
            variant["require_volume"],
            variant["volume_min"],
        )
        if key in event_cache:
            continue
        event_cache[key] = {}
        for symbol in symbols:
            event_cache[key][symbol] = scan_orb(
                frames[variant["timeframe"]][symbol],
                timeframe=variant["timeframe"],
                opening_range_minutes=variant["opening_range_minutes"],
                direction=variant["direction"],
                require_volume=variant["require_volume"],
                volume_min=variant["volume_min"],
                break_buffer_atr=0.05,
                stop_buffer_atr=0.10,
                reward_risk=2.0,
                session_end="15:30",
            )
    rows: list[dict] = []
    trade_rows: list[dict] = []
    baseline_cache: dict[str, dict[str, dict]] = {"15min": {}}
    for window_name, dates in windows_by_timeframe["15min"].items():
        curves = []
        trades = []
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
        baseline_cache["15min"][window_name] = {
            "curve": aggregate_curves(curves),
            "trades": trades,
        }
    for variant in variants:
        timeframe = variant["timeframe"]
        data_by_symbol = frames[timeframe]
        for window_name, dates in windows_by_timeframe[timeframe].items():
            curves = []
            trades = []
            signals = 0
            for symbol in symbols:
                cache_key = (
                    timeframe,
                    variant["opening_range_minutes"],
                    variant["direction"],
                    variant["require_volume"],
                    variant["volume_min"],
                )
                all_events = event_cache[cache_key][symbol]
                window_events = [event for event in all_events if in_window(event["session_date"], dates)]
                signals += sum(gate_allows(event, variant["gate"], regimes) for event in window_events)
                curve, symbol_trades = simulate_orb_symbol(
                    symbol,
                    data_by_symbol[symbol],
                    window_events,
                    dates,
                    variant["gate"],
                    regimes,
                    START_CAPITAL / len(symbols),
                    variant["hold_max_bars"],
                )
                if not curve.empty:
                    curves.append(curve)
                trades.extend(symbol_trades)
                trade_rows.extend(
                    [{**trade, "variant": variant["name"], "window": window_name} for trade in symbol_trades]
                )
            portfolio_curve = aggregate_curves(curves)
            rows.append(
                metric_row(
                    portfolio_curve,
                    trades,
                    variant["name"],
                    timeframe,
                    window_name,
                    signals,
                )
            )
    for window_name, result in baseline_cache["15min"].items():
        rows.append(
            metric_row(
                result["curve"],
                result["trades"],
                "baseline_day_breakout_s78",
                "15min",
                window_name,
                len(result["trades"]),
            )
        )
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = OUT_DIR / "orb_backtests_2026-08-19.csv"
    trades_path = OUT_DIR / "orb_backtest_trades_2026-08-19.csv"
    manifest_path = OUT_DIR / "orb_backtests_2026-08-19_manifest.json"
    pd.DataFrame(rows).to_csv(result_path, index=False)
    pd.DataFrame(trade_rows).to_csv(trades_path, index=False)
    manifest = {
        "source": "real Alpaca IEX caches: 5m structure_mtf_history, 15m volume_profile_history, daily setup_history",
        "symbols": symbols,
        "missing_symbols": missing,
        "windows": windows_by_timeframe,
        "variant_count": len(variants),
        "baseline": "DayBreakout current config + S78 regime bull gate",
        "opening_session": "09:30-16:00 America/New_York; signals through 15:30; premarket excluded",
        "entry": "next bar open after a closed confirmation bar",
        "slippage_bps": 5,
        "commission": 0,
        "overnight": False,
        "options_pnl": False,
        "lookahead": "opening range uses only bars before confirmation; ATR and volume reference are shifted prior bars; regime uses prior daily frame",
        "outputs": [str(result_path), str(trades_path), str(manifest_path)],
    }
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(result_path)
    print(trades_path)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
