"""Backtest de estructura MTF sobre la estrategia live DayBreakout.

Usa barras reales cacheadas de 1d, 15m y 5m, aplica el régimen S78 con datos
anteriores al día evaluado y compara el baseline contra filtros estructurales.
Los resultados son proxy del subyacente: no modelan P&L de opciones.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from risk.regime import apply_crash_cooldown, classify_regime
from strategies.base import SignalType
from strategies.day_trading import DayBreakout
from strategies.structure_mtf import evaluate_structure_mtf

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
DAILY_DIR = ROOT / "backtests/setup_history"
INTRADAY_DIR = ROOT / "backtests/volume_profile_history"
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
    return out.dropna(subset=["open", "high", "low", "close"])


def date_key(value) -> str:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.strftime("%Y-%m-%d")


def previous_daily_frame(frame: pd.DataFrame, day: str) -> pd.DataFrame:
    day_ts = pd.Timestamp(day, tz="UTC")
    return frame.loc[frame.index < day_ts]


def build_regimes(daily: dict[str, pd.DataFrame],
                  symbols: list[str]) -> dict[str, dict]:
    dates = sorted({date_key(index) for symbol in symbols
                    for index in daily[symbol].index})
    states: dict[str, dict] = {}
    bot_state: dict = {}
    for day in dates:
        prior = {symbol: previous_daily_frame(daily[symbol], day)
                 for symbol in symbols}
        regime = classify_regime(prior, symbols)
        regime = apply_crash_cooldown(regime, bot_state,
                                      pd.Timestamp(day).to_pydatetime())
        states[day] = regime
    return states


def closed_frames_for_bar(symbol: str, day: str, bar_time: pd.Timestamp,
                          daily: dict[str, pd.DataFrame],
                          fifteen: dict[str, pd.DataFrame],
                          five: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame | None]:
    # El diario del mismo día todavía no está cerrado. Usar solo días previos.
    daily_frame = previous_daily_frame(daily[symbol], day)
    fifteen_frame = fifteen[symbol].loc[fifteen[symbol].index <= bar_time]
    # Timestamp intradía se interpreta como inicio de barra: para un 15m
    # timestamp t, solo entran 5m con inicio <= t+10m (t+15 sería la barra
    # siguiente), evitando usar una vela futura.
    five_cut = bar_time + pd.Timedelta(minutes=10)
    five_frame = five[symbol].loc[five[symbol].index <= five_cut]
    return {"1d": daily_frame, "15min": fifteen_frame, "5min": five_frame}


def structure_allows(frames: dict[str, pd.DataFrame | None], variant: str) -> bool:
    if variant == "baseline":
        return True
    obs = evaluate_structure_mtf(frames, order=3, tolerance=0.001)
    by_tf = obs["by_timeframe"]
    if variant == "mtf_strict":
        return obs["direction"] == "bull"
    if variant == "daily_bull":
        return by_tf["1d"]["direction"] == "bull"
    if variant == "intraday_bull":
        return (by_tf["15min"]["direction"] == "bull"
                and by_tf["5min"]["direction"] == "bull")
    if variant == "score_positive":
        return obs["score"] > 0.0
    raise ValueError(f"Variante desconocida: {variant}")


def simulate_symbol(symbol: str, fifteen: pd.DataFrame,
                    daily: dict[str, pd.DataFrame],
                    five: dict[str, pd.DataFrame],
                    regimes: dict[str, dict], variant: str,
                    params: dict, initial_capital: float
                    ) -> tuple[pd.Series, list[dict]]:
    strategy = DayBreakout(params)
    initial = initial_capital
    cash = initial
    shares = 0.0
    entry_price = None
    stop_price = None
    bars_held = 0
    pending = None
    trades: list[dict] = []
    equity: dict[pd.Timestamp, float] = {}
    frame = normalise(fifteen)
    if frame is None or len(frame) < 80:
        return pd.Series(dtype=float), trades

    for idx in range(60, len(frame)):
        bar_time = frame.index[idx]
        row = frame.iloc[idx]
        if pending is not None and shares == 0.0 and cash > 0.0:
            fill = float(row["open"]) * (1.0 + SLIPPAGE)
            shares = cash / fill
            cash = 0.0
            entry_price = fill
            stop_price = pending["stop_price"]
            bars_held = 0
            pending = None
        state = {
            "symbol": symbol,
            "entry_price": entry_price,
            "stop_price": stop_price,
            "bars_held": bars_held,
        }
        signal = strategy.scan(frame.iloc[:idx + 1], **state)
        if shares > 0.0:
            bars_held += 1
            if signal.signal_type == SignalType.EXIT:
                if signal.reason == "stop":
                    exit_px = min(float(row["low"]), float(stop_price or row["close"]))
                else:
                    exit_px = float(row["close"])
                exit_px *= 1.0 - SLIPPAGE
                cash = shares * exit_px
                pnl = cash - initial if not trades else cash - trades[-1]["cash_after_entry"]
                trades.append({"symbol": symbol, "entry": entry_price,
                               "exit": exit_px, "pnl": pnl,
                               "reason": signal.reason,
                               "cash_after_entry": cash})
                shares = 0.0
                entry_price = None
                stop_price = None
                bars_held = 0
        elif signal.signal_type == SignalType.LONG:
            regime = regimes.get(date_key(bar_time), {}).get("regime", "cash")
            if regime == "bull":
                frames = closed_frames_for_bar(symbol, date_key(bar_time), bar_time,
                                               daily, {symbol: frame}, five)
                if structure_allows(frames, variant):
                    pending = {"stop_price": float(signal.stop_price or row["close"])}
        mark = cash + shares * float(row["close"])
        equity[bar_time] = mark

    if shares > 0.0 and len(frame):
        last = frame.iloc[-1]
        exit_px = float(last["close"]) * (1.0 - SLIPPAGE)
        cash = shares * exit_px
        trades.append({"symbol": symbol, "entry": entry_price,
                       "exit": exit_px, "pnl": cash - initial,
                       "reason": "end_of_window", "cash_after_entry": cash})
        equity[frame.index[-1]] = cash
    return pd.Series(equity).sort_index(), trades


def metrics(series: pd.Series, trades: list[dict], variant: str,
            window: str) -> dict:
    if series.empty:
        return {"variant": variant, "window": window, "return_pct": None,
                "max_drawdown_pct": None, "trades": 0, "win_rate_pct": None,
                "profit_factor": None, "final_equity": None}
    curve = series.groupby(level=0).last()
    peak = curve.cummax()
    dd = curve / peak - 1.0
    wins = [float(t["pnl"]) for t in trades if t["pnl"] > 0]
    losses = [abs(float(t["pnl"])) for t in trades if t["pnl"] < 0]
    gross_loss = sum(losses)
    return {
        "variant": variant,
        "window": window,
        "return_pct": round((float(curve.iloc[-1]) / START_CAPITAL - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(float(dd.min()) * 100.0, 6),
        "trades": len(trades),
        "win_rate_pct": round(100.0 * len(wins) / len(trades), 6) if trades else None,
        "profit_factor": round(sum(wins) / gross_loss, 6) if gross_loss else None,
        "final_equity": round(float(curve.iloc[-1]), 6),
    }


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol))
             for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(INTRADAY_DIR, symbol))
               for symbol in SYMBOLS}
    five = {symbol: normalise(load_pickle(FIVE_DIR, symbol))
            for symbol in SYMBOLS}
    missing = [symbol for symbol in SYMBOLS
               if daily[symbol] is None or fifteen[symbol] is None or five[symbol] is None]
    symbols = [symbol for symbol in SYMBOLS if symbol not in missing]
    if len(symbols) < 5:
        raise RuntimeError(f"Cobertura insuficiente; faltan: {missing}")
    regimes = build_regimes(daily, symbols)
    available_dates = sorted({date_key(index) for symbol in symbols
                              for index in five[symbol].index})
    if len(available_dates) < 20:
        raise RuntimeError("Menos de 20 días disponibles para backtest MTF")
    # Ventanas recientes basadas en días de trading reales, con una ventana
    # completa y subventanas consecutivas para no declarar ganador a un único
    # tramo.
    windows = {
        "recent_5d": available_dates[-5:],
        "prior_5d": available_dates[-10:-5],
        "prior_10d": available_dates[-20:-10],
        "recent_20d": available_dates[-20:],
        "full_available": available_dates,
    }
    variants = ["baseline", "mtf_strict", "daily_bull", "intraday_bull", "score_positive"]
    rows = []
    for window, dates in windows.items():
        start, end = dates[0], dates[-1]
        for variant in variants:
            book_curves = []
            all_trades = []
            for symbol in symbols:
                window_frame = fifteen[symbol].loc[
                    (fifteen[symbol].index >= pd.Timestamp(start, tz="UTC"))
                    & (fifteen[symbol].index < pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1))
                ]
                curve, trades = simulate_symbol(
                    symbol, window_frame, daily, five, regimes, variant, params,
                    START_CAPITAL / len(symbols))
                if not curve.empty:
                    book_curves.append(curve)
                all_trades.extend(trades)
            if book_curves:
                book = pd.concat(book_curves, axis=1).ffill().fillna(START_CAPITAL / len(SYMBOLS)).sum(axis=1)
            else:
                book = pd.Series(dtype=float)
            rows.append(metrics(book, all_trades, variant, window))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    result_path = OUT_DIR / "structure_mtf_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(result_path, index=False)
    manifest = {
        "source": "real Alpaca IEX 5m + 15m and cached daily OHLCV",
        "symbols": symbols,
        "missing_symbols": missing,
        "variants": variants,
        "windows": {key: [value[0], value[-1], len(value)] for key, value in windows.items()},
        "baseline": "DayBreakout current config + S78 regime bull gate",
        "slippage_bps": 5,
        "options_pnl": False,
        "lookahead": "daily strictly prior date; 5m cutoff at 15m bar end minus 5m; pivots confirmed",
        "output": str(result_path),
    }
    with open(OUT_DIR / "structure_mtf_backtests_2026-08-19_manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(result_path)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
