"""Backtest research-only de la capa completa de trading setups.

Usa datos históricos descargados por MarketDataFeed y solo evalúa cada setup
con barras disponibles hasta el cierre de decisión. Es un proxy direccional del
subyacente, no un backtest de fills de opciones ni una autorización de órdenes.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from data.feed import MarketDataFeed  # noqa: E402
from loop_backtests import UNI_RETO  # noqa: E402
from strategies.setup_confluence import SETUP_NAMES, analyze_setup_confluence  # noqa: E402

OUT = Path(os.environ.get("BACKTEST_MANIFEST_DIR", "/home/ubuntu/backtests"))
OUT.mkdir(parents=True, exist_ok=True)
HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", str(OUT / "setup_history")))

WINDOWS = {
    "lateral_2025": ("2025-09-01", "2025-12-31"),
    "selloff_2026": ("2026-01-01", "2026-04-30"),
    "recent_2026": ("2026-04-01", "2026-08-14"),
    "latest_30d": ("2026-07-01", "2026-08-14"),
}

SCENARIOS = {
    "buy_hold": {"threshold": 0.0, "require_structural": False, "min_confirmations": 0},
    "setup_moderate": {"threshold": 0.35, "require_structural": True, "min_confirmations": 1},
    "setup_strict": {"threshold": 0.55, "require_structural": True, "min_confirmations": 2},
}



def _decision(result: dict, scenario: dict) -> int:
    """Return -1/0/+1 using only the result at the current closed bar."""
    if scenario["threshold"] == 0.0:
        return 1
    direction = result.get("direction")
    if direction not in {"bull", "bear"} or float(result.get("score", 0.0)) < scenario["threshold"]:
        return 0
    observations = result.get("observations", [])
    structural = [
        o for o in observations
        if o.get("setup") in {"key_level", "break_and_retest", "order_block", "bos", "choch", "liquidity_sweep"}
        and o.get("direction") == direction
        and o.get("status") in {"candidate", "confirmed", "context"}
    ]
    confirmations = [
        o for o in observations
        if o.get("setup") in {"ema_cross", "ema_cloud", "vwap", "volume_proxy", "fibonacci_ote", "trendline_channel"}
        and o.get("direction") == direction
        and o.get("status") in {"candidate", "confirmed", "confirmation", "context"}
    ]
    if scenario["require_structural"] and not structural:
        return 0
    if len(confirmations) < scenario["min_confirmations"]:
        return 0
    return 1 if direction == "bull" else -1


def _run_symbol(df: pd.DataFrame, start: str, end: str, scenario: dict) -> tuple[pd.Series, dict, dict, dict]:
    df = df.sort_index().loc[:end].dropna(subset=["open", "close"])
    if len(df) < 80:
        return pd.Series(dtype=float), {"signals": 0, "trades": 0}, {}, {}
    start_ts = pd.Timestamp(start)
    if df.index.tz is not None and start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize(df.index.tz)
    dates = list(df.index)
    positions = []
    signal_counts = {"bull": 0, "bear": 0, "neutral": 0}
    component_counts = {
        name: {"evaluations": 0, "bull": 0, "bear": 0, "neutral": 0, "active": 0}
        for name in SETUP_NAMES
    }
    for i, ts in enumerate(dates[:-1]):
        if scenario["threshold"] == 0.0:
            decision = 1
        else:
            hist = df.iloc[: i + 1]
            result = analyze_setup_confluence("TEST", {"1d": hist}, decision_ts=str(ts))
            decision = _decision(result, scenario)
            direction = result.get("direction", "neutral")
            signal_counts[direction] = signal_counts.get(direction, 0) + 1
            for observation in result.get("observations", []):
                name = observation.get("setup")
                if name not in component_counts:
                    continue
                item = component_counts[name]
                item["evaluations"] += 1
                item[observation.get("direction", "neutral")] += 1
                if observation.get("status") in {"candidate", "confirmed", "confirmation"}:
                    item["active"] += 1
        positions.append(decision)
    returns = []
    return_dates = []
    trades = 0
    prev = 0
    active_signals = 0
    for i, position in enumerate(positions):
        ts = dates[i]
        next_close = float(df.close.iloc[i + 1])
        close_now = float(df.close.iloc[i])
        gross = position * (next_close / close_now - 1.0)
        changed = position != prev
        if abs(position) > 0 and ts >= start_ts:
            active_signals += 1
        if ts >= start_ts:
            if changed:
                trades += 1
                gross -= 0.0005 * abs(position - prev)
            returns.append(gross)
            return_dates.append(dates[i + 1])
        prev = position
    series = pd.Series(returns, index=pd.Index(return_dates, name="timestamp"), dtype=float)
    return series, {"signals": active_signals, "trades": trades}, signal_counts, component_counts


def _load_history() -> tuple[dict[str, pd.DataFrame], list[str]]:
    data = {}
    for symbol in UNI_RETO:
        path = HISTORY_DIR / f"{symbol}.pkl"
        if path.exists():
            data[symbol] = pd.read_pickle(path)
    missing = sorted(set(UNI_RETO) - set(data))
    if missing:
        print(f"Advertencia: faltan históricos cacheados: {','.join(missing)}")
    return data, missing


def _metrics(returns: pd.Series, stats: dict) -> dict:
    if returns.empty:
        return {"return_pct": 0.0, "max_drawdown_pct": 0.0, **stats}
    equity = (1.0 + returns).cumprod()
    drawdown = (equity / equity.cummax() - 1.0).min() * 100.0
    wins = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    return {
        "return_pct": round(float((equity.iloc[-1] - 1.0) * 100.0), 4),
        "max_drawdown_pct": round(float(drawdown), 4),
        "profit_factor": round(float(wins / losses), 4) if losses > 0 else None,
        "positive_days_pct": round(float((returns > 0).mean() * 100.0), 2),
        **stats,
    }


def main() -> None:
    started = time.time()
    data, missing = _load_history()
    if not data:
        feed = MarketDataFeed("yfinance")
        data = feed.history(UNI_RETO, "1d", days=520)
        missing = sorted(set(UNI_RETO) - set(data))
    if not data:
        raise RuntimeError("No hay históricos reales disponibles para el backtest")
    rows = []
    setup_counts = []
    setup_activity = []
    for window, (start, end) in WINDOWS.items():
        for scenario_name, scenario in SCENARIOS.items():
            symbol_returns = []
            total_stats = {"signals": 0, "trades": 0}
            aggregate_direction = {"bull": 0, "bear": 0, "neutral": 0}
            aggregate_components = {
                name: {"evaluations": 0, "bull": 0, "bear": 0, "neutral": 0, "active": 0}
                for name in SETUP_NAMES
            }
            for symbol, df in data.items():
                returns, stats, directions, components = _run_symbol(df, start, end, scenario)
                if not returns.empty:
                    symbol_returns.append(returns.rename(symbol))
                total_stats["signals"] += stats.get("signals", 0)
                total_stats["trades"] += stats.get("trades", 0)
                for key, value in directions.items():
                    aggregate_direction[key] = aggregate_direction.get(key, 0) + value
                for name, values in components.items():
                    for key, value in values.items():
                        aggregate_components[name][key] += value
            if symbol_returns:
                portfolio = pd.concat(symbol_returns, axis=1).fillna(0.0).mean(axis=1)
            else:
                portfolio = pd.Series(dtype=float)
            row = {"window": window, "scenario": scenario_name, "tickers": len(symbol_returns), **_metrics(portfolio, total_stats)}
            rows.append(row)
            setup_counts.append({"window": window, "scenario": scenario_name, **aggregate_direction})
            for name, values in aggregate_components.items():
                setup_activity.append({"window": window, "scenario": scenario_name, "setup": name, **values})
    result_path = OUT / "setup_confluence_backtests_2026-08-18.csv"
    pd.DataFrame(rows).to_csv(result_path, index=False)
    counts_path = OUT / "setup_confluence_direction_counts_2026-08-18.csv"
    pd.DataFrame(setup_counts).to_csv(counts_path, index=False)
    activity_path = OUT / "setup_confluence_component_activity_2026-08-18.csv"
    pd.DataFrame(setup_activity).to_csv(activity_path, index=False)
    manifest_path = OUT / "setup_confluence_backtests_2026-08-18.json"
    manifest_path.write_text(json.dumps({
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": "yfinance via MarketDataFeed",
        "universe_expected": UNI_RETO,
        "universe_used": list(data),
        "missing_tickers": missing,
        "windows": WINDOWS,
        "scenarios": SCENARIOS,
        "proxy_warning": "daily underlying close-to-close proxy; not options fills or broker execution",
        "anti_lookahead": "signal uses bars through t and applies position to t+1 close-to-close return",
        "slippage": "5 bps per unit of position change",
        "results_csv": str(result_path),
        "direction_counts_csv": str(counts_path),
        "component_activity_csv": str(activity_path),
        "setup_names": SETUP_NAMES,
        "elapsed_s": round(time.time() - started, 2),
    }, indent=2) + "\n", encoding="utf-8")
    print(result_path)
    print(counts_path)
    print(activity_path)
    print(manifest_path)


if __name__ == "__main__":
    main()
