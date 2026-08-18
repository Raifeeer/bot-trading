"""Backtest híbrido: configuración actual de Polaris + setups como filtro auxiliar.

El baseline replica la política regime_hold_cash documentada: bull -> exposición
semanal, bear/cash -> efectivo, con crash_event y cooldown. Los candidatos solo
cambian la selección de exposición alcista mediante la confluencia de setups.
Es una proxy de exposición al subyacente, no un P&L de opciones point-in-time.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import get_config  # noqa: E402
from loop_backtests import (  # noqa: E402
    UNI_RETO,
    equity_entry_cost,
    put_choch_entry,
    rsi,
    sma,
)
from strategies.setup_confluence import (  # noqa: E402
    STRUCTURAL_SETUPS,
    analyze_setup_confluence,
)

BASE = Path(os.environ.get("BACKTEST_MANIFEST_DIR", "/home/ubuntu/backtests"))
HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", str(BASE / "setup_history")))
OUT = BASE / "current_setup_integration_2026-08-18"
BASE.mkdir(parents=True, exist_ok=True)

WINDOWS = {
    "lateral_2025": ("2025-09-01", "2025-12-31"),
    "selloff_2026": ("2026-01-01", "2026-04-30"),
    "recent_2026": ("2026-04-01", "2026-08-14"),
    "latest_30d": ("2026-07-01", "2026-08-14"),
}

VARIANTS = {
    "baseline_current": {"kind": "baseline", "timeframe": "none", "threshold": 0.0, "min_confirmations": 0, "selection": "base"},
    "setup_daily_moderate": {"kind": "setup", "timeframe": "daily", "threshold": 0.35, "min_confirmations": 1, "selection": "base"},
    "setup_daily_strict": {"kind": "setup", "timeframe": "daily", "threshold": 0.55, "min_confirmations": 2, "selection": "base"},
    "setup_weekly_moderate": {"kind": "setup", "timeframe": "weekly", "threshold": 0.35, "min_confirmations": 1, "selection": "base"},
    "setup_weekly_strict": {"kind": "setup", "timeframe": "weekly", "threshold": 0.55, "min_confirmations": 2, "selection": "base"},
    "setup_mtf_moderate": {"kind": "setup", "timeframe": "mtf", "threshold": 0.35, "min_confirmations": 1, "selection": "base"},
    "setup_mtf_strict": {"kind": "setup", "timeframe": "mtf", "threshold": 0.55, "min_confirmations": 2, "selection": "base"},
    "setup_mtf_select_strict": {"kind": "setup", "timeframe": "mtf", "threshold": 0.55, "min_confirmations": 2, "selection": "eligible"},
}


def _load_history() -> tuple[dict[str, pd.DataFrame], list[str]]:
    data = {}
    for symbol in UNI_RETO:
        path = HISTORY_DIR / f"{symbol}.pkl"
        if path.exists():
            df = pd.read_pickle(path).sort_index()
            data[symbol] = df
    return data, sorted(set(UNI_RETO) - set(data))


def _norm_day(value) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.normalize()


def _days(data: dict[str, pd.DataFrame], start: str, end: str) -> list[pd.Timestamp]:
    all_days = sorted({_norm_day(ts) for df in data.values() for ts in df.index})
    return [d for d in all_days if _norm_day(start) <= d <= _norm_day(end)]


def _hist(df: pd.DataFrame, day: pd.Timestamp) -> pd.DataFrame:
    return df[df.index.normalize() <= day]


def _weekly(df: pd.DataFrame, decision_day: pd.Timestamp | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    weekly = df.resample("W-FRI").agg({
        "open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
    }).dropna(subset=["close"])
    if decision_day is not None and not weekly.empty:
        day = _norm_day(decision_day)
        weekly = weekly[weekly.index.normalize() <= day]
        if day.weekday() != 4 and len(weekly):
            weekly = weekly.iloc[:-1]
    return weekly


def _regime(data: dict[str, pd.DataFrame], day: pd.Timestamp, crash_lock: pd.Timestamp | None) -> tuple[str, pd.Timestamp | None, dict]:
    bull_count = 0
    bear_count = 0
    n = 0
    crash = 0
    for symbol in UNI_RETO:
        df = data.get(symbol)
        if df is None:
            continue
        sub = _hist(df, day)
        if len(sub) < 110:
            continue
        n += 1
        rs = rsi(sub["close"])
        s200 = sma(sub["close"], 200)
        if pd.notna(rs.iloc[-1]) and rs.iloc[-1] > 50 and pd.notna(s200.iloc[-1]) and sub["close"].iloc[-1] > s200.iloc[-1]:
            bull_count += 1
        if len(sub) >= 60 and put_choch_entry(sub, day) is not None:
            bear_count += 1
        if len(sub) >= 6:
            close_now = float(sub["close"].iloc[-1])
            close_2d = float(sub["close"].iloc[-3])
            if close_2d > 0 and close_now / close_2d - 1.0 <= -0.03:
                crash += 1
    crash_event = n > 0 and crash >= n * 0.30
    if crash_event:
        crash_lock = day
    elif crash_lock is not None and (day - crash_lock).days < 5:
        crash_event = True
    if crash_event or (n > 0 and bear_count >= n * 0.30):
        regime = "bear"
    elif n > 0 and bull_count >= n * 0.50:
        regime = "bull"
    else:
        regime = "cash"
    return regime, crash_lock, {"bull_count": bull_count, "bear_count": bear_count, "n": n, "crash_event": crash_event}


def _observations(data: dict[str, pd.DataFrame], symbol: str, day: pd.Timestamp, timeframe: str) -> dict:
    hist = _hist(data[symbol], day)
    daily = analyze_setup_confluence(symbol, {"1d": hist}, decision_ts=str(day))
    if timeframe == "daily":
        return daily
    weekly = analyze_setup_confluence(symbol, {"1d": _weekly(hist, day)}, decision_ts=str(day))
    if timeframe == "weekly":
        return weekly
    return {"daily": daily, "weekly": weekly}


def _passes(observations: dict, variant: dict) -> tuple[bool, float]:
    if variant["kind"] == "baseline":
        return True, 1.0
    if variant["timeframe"] == "mtf":
        daily = observations["daily"]
        weekly = observations["weekly"]
        if daily.get("direction") != "bull" or weekly.get("direction") != "bull":
            return False, 0.0
        score = (float(daily.get("score", 0.0)) + float(weekly.get("score", 0.0))) / 2.0
        obs = daily.get("observations", []) + weekly.get("observations", [])
    else:
        if observations.get("direction") != "bull":
            return False, 0.0
        score = float(observations.get("score", 0.0))
        obs = observations.get("observations", [])
    if score < variant["threshold"]:
        return False, score
    structural = [
        x for x in obs
        if x.get("setup") in STRUCTURAL_SETUPS
        and x.get("direction") == "bull"
        and x.get("status") in {"candidate", "confirmed", "context"}
    ]
    confirmations = [
        x for x in obs
        if x.get("setup") not in STRUCTURAL_SETUPS
        and x.get("direction") == "bull"
        and x.get("status") in {"candidate", "confirmed", "confirmation", "context"}
    ]
    if not structural or len(confirmations) < variant["min_confirmations"]:
        return False, score
    return True, score


def _mark_equity(equity: float, positions: list[dict], data: dict[str, pd.DataFrame], day: pd.Timestamp, cost_pct: float) -> float:
    marked = float(equity)
    for pos in positions:
        rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == day]
        spot = float(rows["close"].iloc[-1]) if len(rows) else pos["last_spot"]
        value = pos["entry_net"] * spot / pos["entry_spot"] * (1.0 - cost_pct / 2.0)
        marked += value - pos["entry_net"]
    return marked


def _run(data: dict[str, pd.DataFrame], start: str, end: str, variant: dict, config: dict) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    dates = _days(data, start, end)
    if len(dates) < 10:
        return {"return_pct": 0.0, "max_drawdown_pct": 0.0, "trades": 0, "signals": 0}, pd.DataFrame(), pd.DataFrame()
    risk_cfg = config.get("risk", {}) or {}
    exec_cfg = config.get("execution", {}) or {}
    max_pos = int(risk_cfg.get("max_open_positions", 2))
    risk_pct = float(risk_cfg.get("max_risk_per_trade_pct", 5.0)) / 100.0
    cost_pct = 0.002
    slippage_bps = float(exec_cfg.get("slippage_bps", 5.0))
    equity = 100.0
    positions: list[dict] = []
    trades = []
    curve = []
    signal_count = 0
    next_rebal = dates[0]
    crash_lock = None
    regime_counts = {"bull": 0, "bear": 0, "cash": 0}
    for day in dates:
        regime, crash_lock, regime_info = _regime(data, day, crash_lock)
        regime_counts[regime] += 1
        if day >= next_rebal:
            for pos in positions:
                rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == day]
                spot = float(rows["close"].iloc[-1]) if len(rows) else pos["last_spot"]
                value = pos["entry_net"] * spot / pos["entry_spot"] * (1.0 - cost_pct / 2.0)
                pnl = value - pos["entry_net"]
                equity += pnl
                trades.append({"symbol": pos["symbol"], "entry_date": pos["entry_date"], "exit_date": day, "pnl": pnl, "pnl_pct": pnl / pos["entry_net"], "reason": "rebalance_or_regime"})
            positions = []
            if regime == "bull" and not regime_info["crash_event"]:
                base_symbols = sorted(data)[:max_pos]
                candidates = []
                for symbol in sorted(data):
                    observations = _observations(data, symbol, day, variant["timeframe"])
                    passed, score = _passes(observations, variant)
                    if variant["kind"] != "baseline":
                        signal_count += int(passed)
                    if passed:
                        candidates.append((symbol, score))
                if variant["kind"] == "baseline" or variant["selection"] == "base":
                    selected = [s for s in base_symbols if variant["kind"] == "baseline" or any(s == c[0] for c in candidates)]
                else:
                    selected = [s for s, _ in sorted(candidates, key=lambda item: (-item[1], item[0]))[:max_pos]]
                if selected:
                    available = max(0.0, equity)
                    per = min(available / len(selected), available * risk_pct)
                    for symbol in selected:
                        rows = data[symbol][data[symbol].index.normalize() == day]
                        if len(rows) == 0 or per <= 0:
                            continue
                        spot = float(rows["close"].iloc[-1])
                        entry_net = equity_entry_cost(per, {"equity_cost_pct": cost_pct}) * (1.0 + slippage_bps / 10000.0)
                        positions.append({"symbol": symbol, "entry_net": entry_net, "entry_spot": spot, "last_spot": spot, "entry_date": day})
            next_rebal = day + pd.Timedelta(days=7)
        curve.append({"date": day, "equity": _mark_equity(equity, positions, data, day, cost_pct), "open_positions": len(positions), "regime": regime})
    for pos in positions:
        rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == dates[-1]]
        spot = float(rows["close"].iloc[-1]) if len(rows) else pos["last_spot"]
        value = pos["entry_net"] * spot / pos["entry_spot"] * (1.0 - cost_pct / 2.0)
        pnl = value - pos["entry_net"]
        equity += pnl
        trades.append({"symbol": pos["symbol"], "entry_date": pos["entry_date"], "exit_date": dates[-1], "pnl": pnl, "pnl_pct": pnl / pos["entry_net"], "reason": "end_backtest"})
    curve_df = pd.DataFrame(curve)
    if not curve_df.empty:
        eq = curve_df["equity"].astype(float)
        dd = ((eq / eq.cummax()) - 1.0).min() * 100.0
    else:
        dd = 0.0
    trades_df = pd.DataFrame(trades)
    gross_profit = trades_df.loc[trades_df.pnl > 0, "pnl"].sum() if len(trades_df) else 0.0
    gross_loss = -trades_df.loc[trades_df.pnl < 0, "pnl"].sum() if len(trades_df) else 0.0
    return {
        "return_pct": (equity / 100.0 - 1.0) * 100.0,
        "max_drawdown_pct": float(dd),
        "trades": int(len(trades_df)),
        "win_rate_pct": float((trades_df.pnl > 0).mean() * 100.0) if len(trades_df) else 0.0,
        "profit_factor": float(gross_profit / gross_loss) if gross_loss > 0 else None,
        "signals": int(signal_count),
        "time_in_market_pct": float((curve_df.open_positions > 0).mean() * 100.0) if len(curve_df) else 0.0,
        "regime_bull_days": regime_counts["bull"],
        "regime_bear_days": regime_counts["bear"],
        "regime_cash_days": regime_counts["cash"],
    }, curve_df, trades_df


def main() -> None:
    started = time.time()
    data, missing = _load_history()
    if not data:
        raise RuntimeError("No hay históricos reales cacheados")
    config = get_config()
    rows = []
    curves = []
    trades = []
    for window, (start, end) in WINDOWS.items():
        for name, raw_variant in VARIANTS.items():
            variant = {**raw_variant, "name": name}
            metrics, curve, trade_df = _run(data, start, end, variant, config)
            rows.append({"window": window, "start": start, "end": end, "variant": name, **metrics, "tickers": len(data)})
            if len(curve):
                curve.insert(0, "window", window)
                curve.insert(1, "variant", name)
                curves.append(curve)
            if len(trade_df):
                trade_df.insert(0, "window", window)
                trade_df.insert(1, "variant", name)
                trades.append(trade_df)
    results_path = Path(f"{OUT}_results.csv")
    pd.DataFrame(rows).to_csv(results_path, index=False)
    curve_path = Path(f"{OUT}_equity_curves.csv")
    pd.concat(curves, ignore_index=True).to_csv(curve_path, index=False) if curves else curve_path.write_text("\n", encoding="utf-8")
    trades_path = Path(f"{OUT}_trades.csv")
    pd.concat(trades, ignore_index=True).to_csv(trades_path, index=False) if trades else trades_path.write_text("\n", encoding="utf-8")
    manifest = {
        "created_at_utc": pd.Timestamp.now(tz="UTC").isoformat(),
        "source": "cached real OHLCV from MarketDataFeed/yfinance or Alpaca fallback; no synthetic bars",
        "universe_expected": UNI_RETO,
        "universe_used": sorted(data),
        "missing_tickers": missing,
        "windows": WINDOWS,
        "variants": VARIANTS,
        "current_config": {
            "max_open_positions": config.get("risk", {}).get("max_open_positions"),
            "max_risk_per_trade_pct": config.get("risk", {}).get("max_risk_per_trade_pct"),
            "dte_min": config.get("universo", {}).get("options_reto", {}).get("dte_min"),
            "dte_max": config.get("universo", {}).get("options_reto", {}).get("dte_max"),
            "delta_long": config.get("universo", {}).get("options_reto", {}).get("delta_long"),
            "delta_short": config.get("universo", {}).get("options_reto", {}).get("delta_short"),
            "tp_premium_mult": config.get("universo", {}).get("options_reto", {}).get("tp_premium_mult"),
            "sl_premium_mult": config.get("universo", {}).get("options_reto", {}).get("sl_premium_mult"),
        },
        "proxy": "regime_hold_cash current-policy exposure proxy, not point-in-time options P&L",
        "anti_lookahead": "regime and setup use history <= decision day; returns are marked daily and realized on weekly rebalance",
        "costs": {"equity_round_trip_pct": 0.002, "slippage_bps_per_side": 5.0, "alpaca_equity_commission_usd": 0.0},
        "results_csv": str(results_path),
        "equity_curves_csv": str(curve_path),
        "trades_csv": str(trades_path),
        "elapsed_s": round(time.time() - started, 2),
    }
    manifest_path = Path(f"{OUT}_manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(results_path)
    print(curve_path)
    print(trades_path)
    print(manifest_path)


if __name__ == "__main__":
    main()
