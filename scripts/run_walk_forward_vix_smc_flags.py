"""Walk-forward evaluation for VIX, MSS and chart flags.

Selection uses only each fold's training interval. Test intervals are later and
non-overlapping. No variant is connected to production by this script.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts.run_chart_pattern_backtests import _load as load_chart
from scripts.run_chart_pattern_backtests import _simulate as simulate_chart
from scripts.run_chart_pattern_backtests import _stats as stats_chart
from scripts.run_smc_expanded_backtests import _feature_cache
from scripts.run_smc_expanded_backtests import _load as load_smc
from scripts.run_smc_expanded_backtests import _simulate as simulate_smc
from scripts.run_smc_expanded_backtests import _stats as stats_smc
from scripts.run_vix_filter_backtests import VIX_PATH
from scripts.run_vix_filter_backtests import _load as load_vix
from scripts.run_vix_filter_backtests import _simulate as simulate_vix
from scripts.run_vix_filter_backtests import _stats as stats_vix
from strategies.vix_filter import daily_features

ROOT = Path("/home/ubuntu")
OUT = ROOT / "backtests"
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
CAPITAL = 100_000.0
TRAIN_START = pd.Timestamp("2025-08-18", tz="America/New_York")
FOLDS = [
    ("fold_1", pd.Timestamp("2026-03-01", tz="America/New_York"),
     pd.Timestamp("2026-05-01", tz="America/New_York")),
    ("fold_2", pd.Timestamp("2026-05-01", tz="America/New_York"),
     pd.Timestamp("2026-06-01", tz="America/New_York")),
    ("fold_3", pd.Timestamp("2026-06-01", tz="America/New_York"),
     pd.Timestamp("2026-07-16", tz="America/New_York")),
    ("fold_4", pd.Timestamp("2026-07-16", tz="America/New_York"),
     pd.Timestamp("2026-08-19", tz="America/New_York")),
]
FAMILY_VARIANTS = {
    "vix": ["baseline", "percentile_70", "shock_10"],
    "mss": ["baseline", "mss_filter"],
    "flags": ["baseline", "flag_filter", "flag_standalone"],
}


def _portfolio(curves: list[pd.Series], allocation: float) -> pd.Series:
    if not curves:
        return pd.Series(dtype=float)
    return (pd.concat(curves, axis=1).ffill().fillna(allocation).sum(axis=1))


def _evaluate(family: str, variant: str, start: pd.Timestamp, end: pd.Timestamp,
              frames: dict[str, pd.DataFrame], context: dict[str, object]) -> dict[str, float]:
    trades_all: list[dict[str, object]] = []
    curves: list[pd.Series] = []
    allocation = CAPITAL / len(SYMBOLS)
    for symbol, frame in frames.items():
        if family == "vix":
            trades, curve = simulate_vix(
                frame, context["vix_features"], variant, start, end)
        elif family == "mss":
            trades, curve = simulate_smc(
                frame, context["smc_features"][symbol], variant, start, end)
        else:
            trades, curve = simulate_chart(frame, variant, start, end)
        trades_all.extend(trades)
        if not curve.empty:
            curves.append(curve.rename(symbol))
    portfolio = _portfolio(curves, allocation)
    stats = {"return_pct": 0.0, "drawdown_pct": 0.0, "trades": 0.0}
    if family == "vix":
        stats.update(stats_vix(trades_all, portfolio))
    elif family == "mss":
        stats.update(stats_smc(trades_all, portfolio))
    else:
        stats.update(stats_chart(trades_all, portfolio))
    return stats


def _score(stats: dict[str, float]) -> float:
    """Prefer returns but penalize drawdown magnitude during selection."""
    return float(stats["return_pct"] + 0.50 * stats["drawdown_pct"])


def main() -> None:
    frames = {symbol: load_vix(symbol) for symbol in SYMBOLS}
    smc_frames = {symbol: load_smc(symbol) for symbol in SYMBOLS}
    chart_frames = {symbol: load_chart(symbol) for symbol in SYMBOLS}
    vix_features = daily_features(pd.read_pickle(VIX_PATH)["close"])
    context = {
        "vix_features": vix_features,
        "smc_features": {symbol: _feature_cache(frame) for symbol, frame in smc_frames.items()},
    }
    rows: list[dict[str, object]] = []
    for fold, test_start, test_end in FOLDS:
        train_results: dict[str, dict[str, dict[str, float]]] = {}
        for family, variants in FAMILY_VARIANTS.items():
            train_results[family] = {}
            for variant in variants:
                source_frames = frames if family == "vix" else (
                    smc_frames if family == "mss" else chart_frames)
                train_results[family][variant] = _evaluate(
                    family, variant, TRAIN_START, test_start, source_frames, context)
            selected = max(train_results[family],
                           key=lambda variant: _score(train_results[family][variant]))
            source_frames = frames if family == "vix" else (
                smc_frames if family == "mss" else chart_frames)
            selected_test = _evaluate(family, selected, test_start, test_end,
                                      source_frames, context)
            baseline_test = _evaluate(family, "baseline", test_start, test_end,
                                      source_frames, context)
            rows.append({
                "fold": fold,
                "family": family,
                "train_start": str(TRAIN_START.date()),
                "train_end": str(test_start.date()),
                "test_start": str(test_start.date()),
                "test_end": str(test_end.date()),
                "selected_variant": selected,
                "train_selected_return_pct": train_results[family][selected]["return_pct"],
                "train_selected_drawdown_pct": train_results[family][selected]["drawdown_pct"],
                "test_return_pct": selected_test["return_pct"],
                "test_drawdown_pct": selected_test["drawdown_pct"],
                "test_trades": selected_test["trades"],
                "baseline_test_return_pct": baseline_test["return_pct"],
                "baseline_test_drawdown_pct": baseline_test["drawdown_pct"],
                "baseline_test_trades": baseline_test["trades"],
                "test_delta_return_pp": selected_test["return_pct"] - baseline_test["return_pct"],
                "test_delta_drawdown_pp": selected_test["drawdown_pct"] - baseline_test["drawdown_pct"],
                "test_beats_return": selected_test["return_pct"] > baseline_test["return_pct"],
            })
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "walk_forward_vix_smc_flags_2026-08-18.csv", index=False)
    summary = (result.groupby("family", as_index=False)
               .agg(folds=("fold", "count"),
                    mean_test_delta_return_pp=("test_delta_return_pp", "mean"),
                    mean_test_delta_drawdown_pp=("test_delta_drawdown_pp", "mean"),
                    test_return_wins=("test_beats_return", "sum"),
                    selected_variants=("selected_variant", lambda values: ",".join(values))))
    summary.to_csv(OUT / "walk_forward_vix_smc_flags_2026-08-18_summary.csv", index=False)
    manifest = {
        "families": FAMILY_VARIANTS,
        "folds": [(name, str(start.date()), str(end.date())) for name, start, end in FOLDS],
        "train_start": str(TRAIN_START.date()),
        "selection_score": "train_return_pct + 0.50 * train_drawdown_pct",
        "selection_uses_test": False,
        "source": "Alpaca IEX 15m + FRED VIXCLS prior close",
        "production_effect": "none; research only",
    }
    (OUT / "walk_forward_vix_smc_flags_2026-08-18_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
