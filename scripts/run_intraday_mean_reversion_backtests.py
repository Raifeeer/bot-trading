from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import yaml

from scripts.run_orb_backtests import (
    DAILY_DIR,
    FIFTEEN_DIR,
    FIVE_DIR,
    OUT_DIR,
    START_CAPITAL,
    SYMBOLS,
    aggregate_curves,
    build_regimes,
    build_windows,
    in_window,
    load_pickle,
    metric_row,
    normalise,
    prepare_daybreakout,
    simulate_daybreakout,
)
from scripts.run_vwap_backtests import simulate_vwap_fast
from strategies.intraday_mean_reversion import scan_intraday_mean_reversion

ROOT = Path("/home/ubuntu")
BOT = ROOT / "bot-trading"


def variants() -> list[dict]:
    result = []
    for timeframe in ("5min", "15min"):
        for extension_atr in (1.0, 1.5, 2.0):
            for reclaim_atr in (0.25, 0.5):
                for gate in ("none", "bull", "no_crash"):
                    result.append(
                        {
                            "name": f"mr_{timeframe}_ext{str(extension_atr).replace('.', '')}_rec{str(reclaim_atr).replace('.', '')}_{gate}",
                            "timeframe": timeframe,
                            "extension_atr": extension_atr,
                            "reclaim_atr": reclaim_atr,
                            "gate": gate,
                            "hold_max_bars": 12 if timeframe == "5min" else 20,
                        }
                    )
    return result


def scan(frame: pd.DataFrame, variant: dict, regimes: dict[str, dict]) -> list[dict]:
    regime_by_session = {day: info.get("regime", "cash") for day, info in regimes.items()}
    return scan_intraday_mean_reversion(
        frame,
        timeframe=variant["timeframe"],
        extension_atr=variant["extension_atr"],
        reclaim_atr=variant["reclaim_atr"],
        gate=variant["gate"],
        regime_by_session=regime_by_session,
        session_start="09:45",
        session_end="15:15",
        max_hold_bars=variant["hold_max_bars"],
        one_signal_per_session=True,
        allow_shorts=False,
    )


def accepted_events(events: list[dict]) -> list[dict]:
    result = []
    for event in events:
        if event.get("status") != "confirmed":
            continue
        item = dict(event)
        item["break_timestamp"] = pd.Timestamp(event["confirmation_timestamp"])
        result.append(item)
    return result


def main() -> None:
    with open(BOT / "config/config.yaml", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    baseline_params = config["strategies"]["day_breakout"]["params"]
    daily = {symbol: normalise(load_pickle(DAILY_DIR, symbol)) for symbol in SYMBOLS}
    fifteen = {symbol: normalise(load_pickle(FIFTEEN_DIR, symbol)) for symbol in SYMBOLS}
    five = {symbol: normalise(load_pickle(FIVE_DIR, symbol)) for symbol in SYMBOLS}
    missing = [symbol for symbol in SYMBOLS if daily[symbol] is None or fifteen[symbol] is None or five[symbol] is None]
    symbols = [symbol for symbol in SYMBOLS if symbol not in missing]
    daily_used = {symbol: daily[symbol] for symbol in symbols}
    regimes = build_regimes(daily_used, symbols)
    frames = {"5min": {symbol: five[symbol] for symbol in symbols}, "15min": {symbol: fifteen[symbol] for symbol in symbols}}
    windows = {timeframe: build_windows(data, timeframe) for timeframe, data in frames.items()}
    prepared = {symbol: prepare_daybreakout(fifteen[symbol], baseline_params) for symbol in symbols}
    all_variants = variants()
    event_cache = {}
    for variant in all_variants:
        key = (variant["timeframe"], variant["extension_atr"], variant["reclaim_atr"], variant["gate"])
        event_cache[key] = {symbol: scan(frames[variant["timeframe"]][symbol], variant, regimes) for symbol in symbols}
    rows: list[dict] = []
    trades_out: list[dict] = []
    state_rows: list[dict] = []
    for window_name, dates in windows["15min"].items():
        curves, trades = [], []
        for symbol in symbols:
            curve, symbol_trades = simulate_daybreakout(symbol, prepared[symbol], dates, baseline_params, regimes, START_CAPITAL / len(symbols))
            if not curve.empty:
                curves.append(curve)
            trades.extend(symbol_trades)
        rows.append(metric_row(aggregate_curves(curves), trades, "baseline_day_breakout_s78", "15min", window_name, 0))
    for variant in all_variants:
        timeframe = variant["timeframe"]
        key = (timeframe, variant["extension_atr"], variant["reclaim_atr"], variant["gate"])
        for window_name, dates in windows[timeframe].items():
            curves, trades = [], []
            extension_count = confirmed_count = no_reclaim_count = no_edge_count = 0
            for symbol in symbols:
                events = [event for event in event_cache[key][symbol] if in_window(event.get("session_date", ""), dates)]
                extension_count += len(events)
                confirmed_count += sum(event.get("status") == "confirmed" for event in events)
                no_reclaim_count += sum(event.get("status") == "extension_no_reclaim" for event in events)
                no_edge_count += sum(event.get("status") == "confirmation_no_edge" for event in events)
                entries = accepted_events(events)
                curve, symbol_trades = simulate_vwap_fast(symbol, frames[timeframe][symbol], entries, dates, START_CAPITAL / len(symbols), variant["hold_max_bars"])
                if not curve.empty:
                    curves.append(curve)
                trades.extend(symbol_trades)
                trades_out.extend([{**trade, "variant": variant["name"], "window": window_name} for trade in symbol_trades])
            row = metric_row(aggregate_curves(curves), trades, variant["name"], timeframe, window_name, confirmed_count)
            row.update({"extension_events": extension_count, "confirmed_events": confirmed_count, "no_reclaim_events": no_reclaim_count, "no_edge_events": no_edge_count})
            rows.append(row)
            state_rows.append({"variant": variant["name"], "timeframe": timeframe, "window": window_name, "extensions": extension_count, "confirmed": confirmed_count, "no_reclaim": no_reclaim_count, "no_edge": no_edge_count})
    result = OUT_DIR / "intraday_mean_reversion_backtests_2026-08-19.csv"
    pd.DataFrame(rows).to_csv(result, index=False)
    pd.DataFrame(trades_out).to_csv(OUT_DIR / "intraday_mean_reversion_trades_2026-08-19.csv", index=False)
    pd.DataFrame(state_rows).to_csv(OUT_DIR / "intraday_mean_reversion_state_summary_2026-08-19.csv", index=False)
    manifest = {
        "source": "real Alpaca IEX caches: 5m structure_mtf_history and 15m volume_profile_history",
        "symbols": symbols,
        "missing": missing,
        "variants": len(all_variants),
        "extension_atr": [1.0, 1.5, 2.0],
        "reclaim_atr": [0.25, 0.5],
        "gates": ["none", "bull", "no_crash"],
        "entry": "next open after confirmed reclaim",
        "target": "session VWAP at extension",
        "stop": "extension low minus 0.10 ATR",
        "slippage_per_side": 0.0005,
        "allow_shorts": False,
        "outputs": [str(result), str(OUT_DIR / "intraday_mean_reversion_trades_2026-08-19.csv"), str(OUT_DIR / "intraday_mean_reversion_state_summary_2026-08-19.csv")],
    }
    with open(OUT_DIR / "intraday_mean_reversion_manifest_2026-08-19.json", "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    print(json.dumps({"rows": len(rows), "trades": len(trades_out), "variants": len(all_variants), "symbols": symbols}, indent=2))


if __name__ == "__main__":
    main()
