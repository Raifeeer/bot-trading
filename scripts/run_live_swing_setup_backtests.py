"""Backtest del motor live SwingTrend + filtros de trading setups.

Usa el código de `strategies.swing_trading.SwingTrend` para generar entradas,
con ejecución sobre la siguiente barra y gestión de stop/target en barras
posteriores. Es un proxy de equity del subyacente porque no hay cadenas de
opciones point-in-time.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import get_config  # noqa: E402
from loop_backtests import UNI_RETO  # noqa: E402
from strategies.setup_confluence import (  # noqa: E402
    STRUCTURAL_SETUPS,
    analyze_setup_confluence,
)
from strategies.base import SignalType  # noqa: E402
from strategies.swing_trading import SwingTrend  # noqa: E402

BASE = Path(os.environ.get("BACKTEST_MANIFEST_DIR", "/home/ubuntu/backtests"))
HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", str(BASE / "setup_history")))
OUT = BASE / "live_swing_setup_2026-08-18"
WINDOWS = {
    "lateral_2025": ("2025-09-01", "2025-12-31"),
    "selloff_2026": ("2026-01-01", "2026-04-30"),
    "recent_2026": ("2026-04-01", "2026-08-14"),
    "latest_30d": ("2026-07-01", "2026-08-14"),
}
VARIANTS = {
    "swing_baseline": {"kind": "baseline", "timeframe": "none", "threshold": 0.0, "min_confirmations": 0},
    "swing_setup_daily_moderate": {"kind": "setup", "timeframe": "daily", "threshold": 0.35, "min_confirmations": 1},
    "swing_setup_daily_strict": {"kind": "setup", "timeframe": "daily", "threshold": 0.55, "min_confirmations": 2},
    "swing_setup_weekly_moderate": {"kind": "setup", "timeframe": "weekly", "threshold": 0.35, "min_confirmations": 1},
    "swing_setup_weekly_strict": {"kind": "setup", "timeframe": "weekly", "threshold": 0.55, "min_confirmations": 2},
    "swing_setup_mtf_moderate": {"kind": "setup", "timeframe": "mtf", "threshold": 0.35, "min_confirmations": 1},
    "swing_setup_mtf_strict": {"kind": "setup", "timeframe": "mtf", "threshold": 0.55, "min_confirmations": 2},
}


def _norm_day(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.normalize()


def _load() -> tuple[dict[str, pd.DataFrame], list[str]]:
    data = {}
    for symbol in UNI_RETO:
        path = HISTORY_DIR / f"{symbol}.pkl"
        if path.exists():
            data[symbol] = pd.read_pickle(path).sort_index()
    return data, sorted(set(UNI_RETO) - set(data))


def _hist(df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    return df[df.index.normalize() <= day]


def _weekly(df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    out = df.resample("W-FRI").agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna(subset=["close"])
    out = out[out.index.normalize() <= day]
    if day.weekday() != 4 and len(out):
        out = out.iloc[:-1]
    return out


def _observations(symbol: str, df: pd.DataFrame, day: pd.Timestamp, timeframe: str) -> dict:
    hist = _hist(df, day)
    daily = analyze_setup_confluence(symbol, {"1d": hist}, decision_ts=str(day))
    if timeframe == "daily":
        return daily
    weekly = analyze_setup_confluence(symbol, {"1d": _weekly(hist, day)}, decision_ts=str(day))
    if timeframe == "weekly":
        return weekly
    return {"daily": daily, "weekly": weekly}


def _passes(obs: dict, variant: dict) -> bool:
    if variant["kind"] == "baseline":
        return True
    if variant["timeframe"] == "mtf":
        if obs["daily"]["direction"] != "bull" or obs["weekly"]["direction"] != "bull":
            return False
        score = (obs["daily"]["score"] + obs["weekly"]["score"]) / 2.0
        all_obs = obs["daily"]["observations"] + obs["weekly"]["observations"]
    else:
        if obs["direction"] != "bull":
            return False
        score = obs["score"]
        all_obs = obs["observations"]
    if score < variant["threshold"]:
        return False
    structural = [o for o in all_obs if o["setup"] in STRUCTURAL_SETUPS and o["direction"] == "bull" and o["status"] in {"candidate", "confirmed", "context"}]
    confirmations = [o for o in all_obs if o["setup"] not in STRUCTURAL_SETUPS and o["direction"] == "bull" and o["status"] in {"candidate", "confirmed", "confirmation", "context"}]
    return bool(structural) and len(confirmations) >= variant["min_confirmations"]


def _run(data: dict[str, pd.DataFrame], start: str, end: str, variant: dict, params: dict, risk_pct: float, max_pos: int) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    all_days = sorted({_norm_day(ts) for df in data.values() for ts in df.index})
    dates = [d for d in all_days if _norm_day(start) <= d <= _norm_day(end)]
    strategy = SwingTrend(params)
    positions = []
    trades = []
    curve = []
    equity = 100.0
    signals = 0
    for day in dates:
        # Las posiciones se abrieron al cierre de la sesión anterior; la barra
        # actual ya es información disponible para stop/target/salida.
        remaining = []
        for pos in positions:
            df = data[pos["symbol"]]
            rows = df[df.index.normalize() == day]
            if not len(rows):
                remaining.append(pos)
                continue
            bar = rows.iloc[-1]
            held = (day - pos["entry_day"]).days
            reason = ""
            exit_price = float(bar["close"])
            if float(bar["low"]) <= pos["stop_price"]:
                reason, exit_price = "stop", pos["stop_price"]
            elif float(bar["high"]) >= pos["target_price"]:
                reason, exit_price = "target", pos["target_price"]
            else:
                hist = _hist(df, day)
                sig = strategy.scan(hist, symbol=pos["symbol"], entry_price=pos["entry_price"], stop_price=pos["stop_price"], target_price=pos["target_price"], bars_held=held)
                if sig.signal_type == SignalType.EXIT:
                    reason = sig.reason or "strategy_exit"
            if held >= params.get("max_hold_days", 20) and not reason:
                reason = "max_hold"
            if reason:
                gross = pos["notional"] * (exit_price / pos["entry_price"] - 1.0)
                pnl = gross - pos["notional"] * 0.002
                equity += pnl
                trades.append({"symbol": pos["symbol"], "entry_day": pos["entry_day"], "exit_day": day, "pnl": pnl, "pnl_pct": pnl / pos["notional"], "reason": reason})
            else:
                remaining.append(pos)
        positions = remaining
        if len(positions) < max_pos:
            for symbol, df in sorted(data.items()):
                if any(p["symbol"] == symbol for p in positions):
                    continue
                hist = _hist(df, day)
                sig = strategy.scan(hist, symbol=symbol)
                if sig.signal_type != SignalType.LONG:
                    continue
                if not _passes(_observations(symbol, df, day, variant["timeframe"]), variant):
                    continue
                signals += 1
                rows = df[df.index.normalize() == day]
                if not len(rows):
                    continue
                entry_price = float(rows["close"].iloc[-1])
                # La señal se conoce al cierre de day; la entrada efectiva se
                # aproxima al cierre de day y el P&L empieza en la siguiente barra.
                notional = equity * risk_pct
                positions.append({"symbol": symbol, "entry_day": day, "entry_price": entry_price, "notional": notional, "stop_price": float(sig.stop_price), "target_price": float(sig.target_price)})
                if len(positions) >= max_pos:
                    break
        marked = equity
        for pos in positions:
            rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == day]
            if len(rows):
                marked += pos["notional"] * (float(rows["close"].iloc[-1]) / pos["entry_price"] - 1.0)
        curve.append({"date": day, "equity": marked, "open_positions": len(positions)})
    for pos in positions:
        rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == dates[-1]]
        if len(rows):
            exit_price = float(rows["close"].iloc[-1])
            pnl = pos["notional"] * (exit_price / pos["entry_price"] - 1.0) - pos["notional"] * 0.002
            equity += pnl
            trades.append({"symbol": pos["symbol"], "entry_day": pos["entry_day"], "exit_day": dates[-1], "pnl": pnl, "pnl_pct": pnl / pos["notional"], "reason": "end_backtest"})
    curve_df = pd.DataFrame(curve)
    trades_df = pd.DataFrame(trades)
    if len(curve_df):
        dd = ((curve_df.equity / curve_df.equity.cummax()) - 1.0).min() * 100.0
    else:
        dd = 0.0
    gp = trades_df.loc[trades_df.pnl > 0, "pnl"].sum() if len(trades_df) else 0.0
    gl = -trades_df.loc[trades_df.pnl < 0, "pnl"].sum() if len(trades_df) else 0.0
    return {"return_pct": equity - 100.0, "max_drawdown_pct": dd, "trades": len(trades_df), "win_rate_pct": (trades_df.pnl > 0).mean() * 100.0 if len(trades_df) else 0.0, "profit_factor": gp / gl if gl > 0 else None, "signals": signals, "time_in_market_pct": (curve_df.open_positions > 0).mean() * 100.0 if len(curve_df) else 0.0}, curve_df, trades_df


def main() -> None:
    data, missing = _load()
    if not data:
        raise RuntimeError("No hay históricos reales cacheados")
    config = get_config()
    params = config.get("strategies", {}).get("swing_trend", {}).get("params", {})
    risk_cfg = config.get("risk", {}) or {}
    risk_pct = float(risk_cfg.get("max_risk_per_trade_pct", 5.0)) / 100.0
    max_pos = int(risk_cfg.get("max_open_positions", 2))
    rows, curves, trades = [], [], []
    for window, (start, end) in WINDOWS.items():
        for name, variant in VARIANTS.items():
            metrics, curve, trade_df = _run(data, start, end, variant, params, risk_pct, max_pos)
            rows.append({"window": window, "start": start, "end": end, "variant": name, **metrics, "tickers": len(data)})
            if len(curve):
                curve.insert(0, "window", window)
                curve.insert(1, "variant", name)
                curves.append(curve)
            if len(trade_df):
                trade_df.insert(0, "window", window)
                trade_df.insert(1, "variant", name)
                trades.append(trade_df)
    result_path = Path(f"{OUT}_results.csv")
    pd.DataFrame(rows).to_csv(result_path, index=False)
    pd.concat(curves, ignore_index=True).to_csv(f"{OUT}_equity_curves.csv", index=False)
    pd.concat(trades, ignore_index=True).to_csv(f"{OUT}_trades.csv", index=False) if trades else Path(f"{OUT}_trades.csv").write_text("\n", encoding="utf-8")
    manifest = {"source": "real cached daily OHLCV; no synthetic bars", "universe_expected": UNI_RETO, "universe_used": sorted(data), "missing_tickers": missing, "windows": WINDOWS, "variants": VARIANTS, "engine": "strategies.swing_trading.SwingTrend exact live signal code", "current_config": {"swing_params": params, "max_risk_per_trade_pct": risk_cfg.get("max_risk_per_trade_pct"), "max_open_positions": risk_cfg.get("max_open_positions")}, "execution": "signal at close of day t, next-bar path for existing positions; 0.2% round-trip equity cost", "options_limit": "equity proxy; no point-in-time option chains, bid/ask or fills"}
    Path(f"{OUT}_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(result_path)


if __name__ == "__main__":
    main()
