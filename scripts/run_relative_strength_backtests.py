from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from risk.regime import apply_crash_cooldown, classify_regime
from strategies.relative_strength_rotation import evaluate_relative_strength

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"
DAILY_DIR = ROOT / "backtests/setup_history"
OUT_DIR = ROOT / "backtests"
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
START_CAPITAL = 100_000.0


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
    if "close" not in out.columns:
        return None
    out = out.dropna(subset=["close"])
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
    dates = sorted({date_key(index) for symbol in symbols for index in daily[symbol].index})
    states: dict[str, dict] = {}
    bot_state: dict = {}
    for day in dates:
        prior = {symbol: previous_daily_frame(daily[symbol], day) for symbol in symbols}
        regime = classify_regime(prior, symbols)
        states[day] = apply_crash_cooldown(regime, bot_state, pd.Timestamp(day).to_pydatetime())
    return states


def build_windows(dates: list[str]) -> dict[str, list[str]]:
    if len(dates) < 140:
        raise RuntimeError(f"Cobertura diaria insuficiente: {len(dates)} sesiones")
    return {
        "recent_20d": dates[-20:],
        "prior_20d": dates[-40:-20],
        "prior_40d": dates[-80:-40],
        "recent_60d": dates[-60:],
        "recent_120d": dates[-120:],
        "full_available": dates,
    }


def close_map(frames: dict[str, pd.DataFrame], dates: list[str]) -> dict[str, dict[str, float]]:
    result: dict[str, dict[str, float]] = {}
    for symbol, frame in frames.items():
        result[symbol] = {
            str(day): float(row["close"])
            for day, row in frame.groupby("session_date").last().iterrows()
            if dates[0] <= str(day) <= dates[-1]
        }
    return result


def choose_weights(
    observations: list[dict],
    *,
    mode: str,
    top_k: int,
    gate: str,
    regime: str,
    only_positive: bool,
) -> dict[str, float]:
    if gate == "bull" and regime != "bull":
        return {}
    leaders = [
        item
        for item in observations
        if item.get("direction") == "bull"
        and item.get("percentile") is not None
        and float(item["percentile"]) >= 0.75
        and (not only_positive or float(item["return_formation"]) > 0)
    ]
    leaders.sort(key=lambda item: float(item["excess_return"]), reverse=True)
    selected = leaders[:top_k]
    if not selected:
        return {}
    if mode == "long_only":
        weight = 1.0 / len(selected)
        return {item["symbol"]: weight for item in selected}
    laggards = [
        item
        for item in observations
        if item.get("direction") == "bear"
        and item.get("percentile") is not None
        and float(item["percentile"]) <= 0.25
        and float(item["return_formation"]) < 0
    ]
    laggards.sort(key=lambda item: float(item["excess_return"]))
    selected_laggards = laggards[:top_k]
    weights: dict[str, float] = {}
    if selected:
        long_weight = 0.5 / len(selected_laggards or selected)
        weights.update({item["symbol"]: long_weight for item in selected})
    if selected_laggards:
        short_weight = -0.5 / len(selected_laggards)
        weights.update({item["symbol"]: short_weight for item in selected_laggards})
    return weights


def simulate_variant(
    frames: dict[str, pd.DataFrame],
    dates: list[str],
    window_dates: list[str],
    regimes: dict[str, dict],
    snapshots: dict[tuple[str, int], list[dict]],
    *,
    horizon: int,
    top_k: int,
    rebalance_days: int,
    gate: str,
    mode: str,
    only_positive: bool,
    cost_bps: float,
) -> tuple[pd.Series, dict[str, float]]:
    first_idx = dates.index(window_dates[0])
    last_idx = dates.index(window_dates[-1])
    start_idx = max(0, first_idx - horizon - rebalance_days - 5)
    prices = close_map(frames, dates)
    equity = START_CAPITAL
    weights: dict[str, float] = {}
    curve: dict[pd.Timestamp, float] = {}
    turnover = 0.0
    rebalance_count = 0
    exposure_sum = 0.0
    exposure_count = 0
    for idx in range(start_idx, last_idx + 1):
        day = dates[idx]
        if idx > start_idx:
            previous_day = dates[idx - 1]
            portfolio_return = 0.0
            for symbol, weight in weights.items():
                prev_price = prices.get(symbol, {}).get(previous_day)
                current_price = prices.get(symbol, {}).get(day)
                if prev_price and current_price:
                    portfolio_return += weight * (current_price / prev_price - 1.0)
            equity *= 1.0 + portfolio_return
        if idx >= first_idx:
            timestamp = pd.Timestamp(day, tz="America/New_York").tz_convert("UTC")
            curve[timestamp] = equity
            exposure_sum += sum(abs(weight) for weight in weights.values())
            exposure_count += 1
        if idx < last_idx and (idx - start_idx) % rebalance_days == 0:
            new_weights = choose_weights(
                snapshots[(day, horizon)],
                mode=mode,
                top_k=top_k,
                gate=gate,
                regime=regimes.get(day, {}).get("regime", "cash"),
                only_positive=only_positive,
            )
            symbols_union = set(weights) | set(new_weights)
            turnover += sum(abs(new_weights.get(symbol, 0.0) - weights.get(symbol, 0.0)) for symbol in symbols_union)
            equity *= max(0.0, 1.0 - sum(abs(new_weights.get(symbol, 0.0) - weights.get(symbol, 0.0)) for symbol in symbols_union) * cost_bps / 10_000.0)
            weights = new_weights
            rebalance_count += 1
    metrics = {
        "turnover_one_way": turnover,
        "rebalances": rebalance_count,
        "mean_abs_exposure": exposure_sum / exposure_count if exposure_count else 0.0,
    }
    return pd.Series(curve).sort_index(), metrics


def metric_row(curve: pd.Series, variant: str, window: str, extra: dict[str, float]) -> dict:
    if curve.empty:
        return {"variant": variant, "window": window, "return_pct": None, "max_drawdown_pct": None, "final_equity": None, **extra}
    peak = curve.cummax()
    drawdown = curve / peak - 1.0
    return {
        "variant": variant,
        "window": window,
        "return_pct": round((float(curve.iloc[-1]) / START_CAPITAL - 1.0) * 100.0, 6),
        "max_drawdown_pct": round(float(drawdown.min()) * 100.0, 6),
        "final_equity": round(float(curve.iloc[-1]), 6),
        **extra,
    }


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        yaml.safe_load(handle)
    raw = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    missing = [symbol for symbol in SYMBOLS if raw[symbol] is None]
    symbols = [symbol for symbol in SYMBOLS if symbol not in missing]
    frames = {symbol: raw[symbol] for symbol in symbols}
    all_dates = sorted({day for frame in frames.values() for day in frame["session_date"].unique()})
    regimes = build_regimes(frames, symbols)
    windows = build_windows(all_dates)
    horizons = (20, 60)
    snapshots: dict[tuple[str, int], list[dict]] = {}
    for day in all_dates:
        asof = pd.Timestamp(day, tz="America/New_York").tz_convert("UTC") + pd.Timedelta(hours=23)
        for horizon in horizons:
            result = evaluate_relative_strength(
                frames,
                horizon_bars=horizon,
                top_percentile=0.75,
                bottom_percentile=0.25,
                only_positive=False,
                allow_shorts=True,
                asof_timestamp=asof,
            )
            snapshots[(day, horizon)] = result["observations"]
    variants = []
    for horizon in horizons:
        for top_k in (1, 2):
            for rebalance_days in (1, 5):
                for gate in ("none", "bull"):
                    for mode in ("long_only", "long_short"):
                        for only_positive in (False, True):
                            for cost_bps in (5.0, 10.0, 20.0):
                                variants.append(
                                    {
                                        "name": f"rs_h{horizon}_k{top_k}_r{rebalance_days}_{gate}_{mode}_{'pos' if only_positive else 'all'}_c{int(cost_bps)}",
                                        "horizon": horizon,
                                        "top_k": top_k,
                                        "rebalance_days": rebalance_days,
                                        "gate": gate,
                                        "mode": mode,
                                        "only_positive": only_positive,
                                        "cost_bps": cost_bps,
                                    }
                                )
    rows = []
    benchmark_variants = {
        "baseline_equal_weight": {"mode": "equal_weight"},
        "baseline_regime_s78": {"mode": "regime_s78"},
    }
    for name, baseline in benchmark_variants.items():
        for window_name, window_dates in windows.items():
            if baseline["mode"] == "equal_weight":
                weights = {symbol: 1.0 / len(symbols) for symbol in symbols}
                gate = "none"
            else:
                weights = {}
                gate = "bull"
            # Reuse the simulation machinery with a temporary all-leader snapshot is not safe;
            # construct direct baseline curves to keep the benchmark semantics explicit.
            prices = close_map(frames, all_dates)
            equity = START_CAPITAL
            curve = {}
            first_idx, last_idx = all_dates.index(window_dates[0]), all_dates.index(window_dates[-1])
            for idx in range(first_idx, last_idx + 1):
                day = all_dates[idx]
                if idx > first_idx:
                    prev = all_dates[idx - 1]
                    if baseline["mode"] == "regime_s78":
                        state = regimes.get(prev, {}).get("regime", "cash")
                        active_weights = {symbol: 1.0 / len(symbols) for symbol in symbols} if state == "bull" else {}
                    else:
                        active_weights = weights
                    ret = sum(
                        weight * (prices[symbol][day] / prices[symbol][prev] - 1.0)
                        for symbol, weight in active_weights.items()
                        if day in prices[symbol] and prev in prices[symbol]
                    )
                    equity *= 1.0 + ret
                curve[pd.Timestamp(day, tz="America/New_York").tz_convert("UTC")] = equity
            rows.append(metric_row(pd.Series(curve), name, window_name, {"turnover_one_way": 0.0, "rebalances": 0, "mean_abs_exposure": 1.0 if name == "baseline_equal_weight" else None, "horizon": None, "top_k": None, "rebalance_days": None, "gate": gate, "mode": baseline["mode"], "only_positive": None, "cost_bps": 0.0}))
    for variant in variants:
        for window_name, window_dates in windows.items():
            curve, extra = simulate_variant(
                frames,
                all_dates,
                window_dates,
                regimes,
                snapshots,
                horizon=variant["horizon"],
                top_k=variant["top_k"],
                rebalance_days=variant["rebalance_days"],
                gate=variant["gate"],
                mode=variant["mode"],
                only_positive=variant["only_positive"],
                cost_bps=variant["cost_bps"],
            )
            rows.append(metric_row(curve, variant["name"], window_name, {**extra, **{key: variant[key] for key in ("horizon", "top_k", "rebalance_days", "gate", "mode", "only_positive", "cost_bps")}}))
    output = OUT_DIR / "relative_strength_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(output, index=False)
    manifest = {
        "date": "2026-08-19",
        "symbols_requested": SYMBOLS,
        "symbols_used": symbols,
        "missing_symbols": missing,
        "windows": windows,
        "horizons": horizons,
        "variants": len(variants),
        "benchmark": "equal_weight_universe; no SPY/QQQ cache available",
        "cost_bps": [5.0, 10.0, 20.0],
        "anti_lookahead": [
            "ranking uses closes through current date and applies next-date return",
            "benchmark uses same available symbols as ranking",
            "regime uses prior daily frames",
            "window metrics use historical warmup but start at window date",
        ],
        "output": str(output),
    }
    with open(OUT_DIR / "relative_strength_backtest_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(json.dumps({"rows": len(rows), "variants": len(variants), "symbols": symbols}, indent=2))


if __name__ == "__main__":
    main()
