"""Analiza el motor bearish y lo compara con DayBreakout baseline."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from scripts.run_bearish_breakdown_retest_backtests import (
    DAILY_DIR,
    FIFTEEN_DIR,
    FIVE_DIR,
    OUT,
    SYMBOLS,
    build_regimes,
    event_day,
    load_pickle,
    normalise,
    rth,
    window_map,
)
from scripts.run_structure_mtf_backtests import simulate_symbol

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
START_CAPITAL = 100_000.0


def curve_metrics(curve: pd.Series, label: str, window: str, trades: int) -> dict[str, Any]:
    if curve.empty:
        return {"variant": label, "window": window, "return_pct": None, "max_drawdown_pct": None, "trades": trades}
    peak = curve.cummax()
    dd = curve / peak - 1.0
    return {
        "variant": label,
        "window": window,
        "return_pct": round((float(curve.iloc[-1]) / START_CAPITAL - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(float(dd.min()) * 100.0, 6),
        "trades": trades,
    }


def compute_baseline(
    daily: dict[str, pd.DataFrame],
    fifteen: dict[str, pd.DataFrame],
    five: dict[str, pd.DataFrame],
    regimes: dict[str, dict],
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        params = yaml.safe_load(handle)["strategies"]["day_breakout"]["params"]
    rows: list[dict[str, Any]] = []
    symbols = sorted(fifteen)
    for window, days in windows.items():
        day_set = set(days)
        curves: list[pd.Series] = []
        trade_count = 0
        for symbol in symbols:
            frame = fifteen[symbol].loc[fifteen[symbol].index.map(event_day).isin(day_set)]
            curve, trades = simulate_symbol(
                symbol,
                frame,
                daily,
                five,
                regimes,
                "baseline",
                params,
                START_CAPITAL / len(symbols),
            )
            if not curve.empty:
                curves.append(curve)
            trade_count += len(trades)
        if curves:
            book = pd.concat(curves, axis=1).ffill().fillna(START_CAPITAL / len(symbols)).sum(axis=1)
        else:
            book = pd.Series(dtype=float)
        rows.append(curve_metrics(book, "daybreakout_baseline", window, trade_count))
    return pd.DataFrame(rows)


def aggregate_candidates(raw: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (variant, window, gated), group in raw.groupby(["variant", "window", "gated"], dropna=False):
        returns = group["return_pct"].astype(float)
        drawdowns = group["max_drawdown_pct"].astype(float)
        rows.append({
            "variant": variant,
            "window": window,
            "gated": bool(gated),
            "return_pct_mean_symbols": round(float(returns.mean()), 6),
            "return_pct_portfolio_equal_weight": round(float(returns.mean()), 6),
            "max_drawdown_mean_symbols": round(float(drawdowns.mean()), 6),
            "max_drawdown_worst_symbol": round(float(drawdowns.min()), 6),
            "trades_sum": int(group["trades"].sum()),
            "symbols_with_trades": int((group["trades"] > 0).sum()),
            "signals_confirmed_sum": int(group["signals_confirmed"].sum()),
            "win_rate_mean": round(float(group["win_rate_pct"].dropna().mean()), 6) if group["win_rate_pct"].notna().any() else None,
        })
    return pd.DataFrame(rows)


def main() -> None:
    raw_path = OUT / "bearish_breakdown_retest_backtests_2026-08-19.csv"
    raw = pd.read_csv(raw_path)
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: rth(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    five = {symbol: rth(load_pickle(FIVE_DIR, symbol)) for symbol in SYMBOLS}
    symbols = [symbol for symbol in SYMBOLS if daily[symbol] is not None and fifteen[symbol] is not None and five[symbol] is not None]
    daily = {symbol: daily[symbol] for symbol in symbols}
    fifteen = {symbol: fifteen[symbol] for symbol in symbols}
    five = {symbol: five[symbol] for symbol in symbols}
    regimes = build_regimes(daily, symbols)
    windows = window_map(fifteen, n_days=60)
    candidate_summary = aggregate_candidates(raw)
    baseline = compute_baseline(daily, fifteen, five, regimes, windows)
    baseline_path = OUT / "bearish_breakdown_retest_baseline_2026-08-19.csv"
    baseline.to_csv(baseline_path, index=False)
    summary_path = OUT / "bearish_breakdown_retest_portfolio_summary_2026-08-19.csv"
    candidate_summary.to_csv(summary_path, index=False)
    comparison_rows: list[dict[str, Any]] = []
    for _, candidate in candidate_summary.iterrows():
        base = baseline.loc[baseline["window"] == candidate["window"]]
        if base.empty:
            continue
        base_row = base.iloc[0]
        comparison_rows.append({
            **candidate.to_dict(),
            "baseline_return_pct": float(base_row["return_pct"]),
            "baseline_drawdown_pct": float(base_row["max_drawdown_pct"]),
            "delta_return_vs_baseline": round(float(candidate["return_pct_portfolio_equal_weight"]) - float(base_row["return_pct"]), 6),
            "delta_drawdown_mean_vs_baseline": round(float(candidate["max_drawdown_mean_symbols"]) - float(base_row["max_drawdown_pct"]), 6),
        })
    comparison = pd.DataFrame(comparison_rows)
    comparison_path = OUT / "bearish_breakdown_retest_comparison_2026-08-19.csv"
    comparison.to_csv(comparison_path, index=False)
    variant_summary = (
        comparison.groupby(["variant", "gated"], as_index=False)
        .agg(
            mean_return_pct=("return_pct_portfolio_equal_weight", "mean"),
            positive_windows=("delta_return_vs_baseline", lambda values: int((values > 0).sum())),
            windows=("delta_return_vs_baseline", "count"),
            mean_delta_return=("delta_return_vs_baseline", "mean"),
            mean_delta_drawdown=("delta_drawdown_mean_vs_baseline", "mean"),
            total_trades=("trades_sum", "sum"),
        )
    )
    variant_summary["mean_return_pct"] = variant_summary["mean_return_pct"].round(6)
    variant_summary["mean_delta_return"] = variant_summary["mean_delta_return"].round(6)
    variant_summary["mean_delta_drawdown"] = variant_summary["mean_delta_drawdown"].round(6)
    variant_summary_path = OUT / "bearish_breakdown_retest_variant_summary_2026-08-19.csv"
    variant_summary.to_csv(variant_summary_path, index=False)
    manifest = {
        "source_results": str(raw_path),
        "baseline": "DayBreakout current config + S78 bull gate, same real bars and seven symbols",
        "candidate_aggregation": "equal-weight mean of per-symbol return proxies; used as a screening comparison against the same seven-symbol baseline",
        "missing_symbols": [symbol for symbol in SYMBOLS if symbol not in symbols],
        "outputs": [str(summary_path), str(baseline_path), str(comparison_path), str(variant_summary_path)],
    }
    with open(OUT / "bearish_breakdown_retest_analysis_2026-08-19_manifest.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(json.dumps(manifest, indent=2))
    print(variant_summary.sort_values("mean_delta_return", ascending=False).to_string(index=False))


if __name__ == "__main__":
    main()
