"""Backtest parcial de SMC ampliado sobre DayBreakout.

Se limita a 15m porque es la única cobertura intradía histórica completa
cacheada. No afirma validar la cascada 1D/4H/15M/5M ni modela P&L de opciones.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from strategies.smc_expanded import snapshot

ROOT = Path("/home/ubuntu")
HISTORY = ROOT / "backtests/volume_profile_history"
OUT = ROOT / "backtests"
CAPITAL = 100_000.0
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
DONCHIAN_PERIOD = 10
ATR_PERIOD = 14
ATR_STOP_MULT = 2.5
HOLD_MAX_BARS = 20
SLIPPAGE_BPS = 5.0
ENTRY_START = "10:00"
ENTRY_END = "15:30"
VARIANTS = ["baseline", "fvg_filter", "mss_filter", "ob_sweep", "confluence"]


def _load(symbol: str) -> pd.DataFrame:
    frame = pd.read_pickle(HISTORY / f"{symbol}.pkl").copy()
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert("America/New_York")
    frame = frame.sort_index()
    frame["atr"] = _atr(frame)
    frame["donch_hi"] = frame["high"].shift(1).rolling(DONCHIAN_PERIOD).max()
    frame["donch_lo"] = frame["low"].shift(1).rolling(DONCHIAN_PERIOD).min()
    return frame.dropna(subset=["open", "high", "low", "close", "volume"])


def _atr(frame: pd.DataFrame) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat(
        [frame["high"] - frame["low"],
         (frame["high"] - prev).abs(),
         (frame["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _windows(last: pd.Timestamp) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    end = last.normalize() + pd.Timedelta(days=1)
    return {
        "selloff_spring_2026": (pd.Timestamp("2026-03-01", tz=end.tz),
                                pd.Timestamp("2026-04-30", tz=end.tz) + pd.Timedelta(days=1)),
        "recovery_may_2026": (pd.Timestamp("2026-05-01", tz=end.tz),
                              pd.Timestamp("2026-05-31", tz=end.tz) + pd.Timedelta(days=1)),
        "summer_2026": (pd.Timestamp("2026-06-01", tz=end.tz), end),
        "latest_30d": (end - pd.Timedelta(days=30), end),
        "full_recent": (end - pd.Timedelta(days=365), end),
    }


def _feature_cache(frame: pd.DataFrame) -> dict[int, dict[str, object]]:
    cache: dict[int, dict[str, object]] = {}
    for i in range(DONCHIAN_PERIOD + ATR_PERIOD + 20, len(frame)):
        row = frame.iloc[i]
        if pd.isna(row["donch_hi"]) or float(row["close"]) <= float(row["donch_hi"]):
            continue
        context = frame.iloc[max(0, i - 180):i + 1][["open", "high", "low", "close", "volume"]]
        cache[i] = snapshot(context)
    return cache


def _allowed(variant: str, features: dict[str, object]) -> bool:
    if variant == "baseline":
        return True
    fvg = bool(features.get("fvg_bull"))
    mss = bool(features.get("mss")) and features.get("bos") == "bull"
    ob = bool(features.get("ob_bull"))
    sweep = bool(features.get("sweep_bull"))
    if variant == "fvg_filter":
        return fvg
    if variant == "mss_filter":
        return mss
    if variant == "ob_sweep":
        return ob and sweep
    if variant == "confluence":
        return sum([fvg, mss, ob, sweep]) >= 2
    raise ValueError(f"Variante desconocida: {variant}")


def _simulate(frame: pd.DataFrame, features: dict[int, dict[str, object]],
              variant: str, start: pd.Timestamp, end: pd.Timestamp) -> tuple[list[dict[str, object]], pd.Series]:
    data = frame[(frame.index >= start) & (frame.index < end)]
    allocation = CAPITAL / len(SYMBOLS)
    cash = allocation
    shares = 0.0
    entry_price = None
    stop_price = None
    entry_ts = None
    bars_held = 0
    trades: list[dict[str, object]] = []
    curve: list[tuple[pd.Timestamp, float]] = []
    last_day = None
    last_mark = allocation
    for i, (ts, row) in enumerate(data.iterrows()):
        original_i = frame.index.get_loc(ts)
        if last_day is not None and ts.date() != last_day:
            curve.append((pd.Timestamp(last_day, tz=ts.tz), last_mark))
        close = float(row["close"])
        if shares > 0:
            bars_held += 1
            stop_hit = float(row["low"]) <= float(stop_price)
            fallback = pd.notna(row["donch_lo"]) and close < float(row["donch_lo"])
            max_hold = bars_held >= HOLD_MAX_BARS
            if stop_hit or fallback or max_hold:
                exit_price = float(stop_price) if stop_hit else close
                exit_price *= 1.0 - SLIPPAGE_BPS / 10_000.0
                pnl = shares * (exit_price - float(entry_price))
                cash += shares * exit_price
                trades.append({"entry_ts": entry_ts, "exit_ts": ts,
                               "entry_price": entry_price, "exit_price": exit_price,
                               "pnl": pnl, "reason": "stop" if stop_hit else
                               ("fallback" if fallback else "max_hold"), "bars": bars_held})
                shares = 0.0
                entry_price = None
                stop_price = None
                entry_ts = None
                bars_held = 0
        in_session = ENTRY_START <= ts.strftime("%H:%M") < ENTRY_END
        if (shares == 0 and in_session and original_i in features
                and _allowed(variant, features[original_i])):
            atr = float(row["atr"]) if pd.notna(row["atr"]) else 0.0
            if atr > 0:
                entry_price = close * (1.0 + SLIPPAGE_BPS / 10_000.0)
                shares = allocation / entry_price
                cash -= shares * entry_price
                stop_price = max(0.01, close - ATR_STOP_MULT * atr)
                entry_ts = ts
                bars_held = 0
        last_day = ts.date()
        last_mark = cash + shares * close
    if last_day is not None:
        curve.append((pd.Timestamp(last_day, tz=data.index.tz), last_mark))
    if shares > 0:
        ts = data.index[-1]
        exit_price = float(data.iloc[-1]["close"]) * (1.0 - SLIPPAGE_BPS / 10_000.0)
        pnl = shares * (exit_price - float(entry_price))
        cash += shares * exit_price
        trades.append({"entry_ts": entry_ts, "exit_ts": ts,
                       "entry_price": entry_price, "exit_price": exit_price,
                       "pnl": pnl, "reason": "window_end", "bars": bars_held})
        curve[-1] = (ts, cash)
    return trades, pd.Series(dict(curve)).sort_index()


def _stats(trades: list[dict[str, object]], curve: pd.Series) -> dict[str, float]:
    if curve.empty:
        return {"return_pct": 0.0, "drawdown_pct": 0.0, "trades": 0.0,
                "win_rate_pct": 0.0, "profit_factor": 0.0}
    drawdown = curve / curve.cummax() - 1.0
    pnl = pd.Series([float(t["pnl"]) for t in trades]) if trades else pd.Series(dtype=float)
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return {"return_pct": float((curve.iloc[-1] / CAPITAL - 1.0) * 100.0),
            "drawdown_pct": float(drawdown.min() * 100.0),
            "trades": float(len(trades)),
            "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else 0.0,
            "profit_factor": float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)}


def main() -> None:
    frames = {symbol: _load(symbol) for symbol in SYMBOLS}
    features = {symbol: _feature_cache(frame) for symbol, frame in frames.items()}
    last = max(frame.index.max() for frame in frames.values())
    rows: list[dict[str, object]] = []
    for window, (start, end) in _windows(last).items():
        for variant in VARIANTS:
            trades_all: list[dict[str, object]] = []
            curves = []
            for symbol, frame in frames.items():
                trades, curve = _simulate(frame, features[symbol], variant, start, end)
                trades_all.extend({**trade, "symbol": symbol} for trade in trades)
                if not curve.empty:
                    curves.append(curve.rename(symbol))
            portfolio = (pd.concat(curves, axis=1).ffill()
                         .fillna(CAPITAL / len(SYMBOLS)).sum(axis=1)) if curves else pd.Series(dtype=float)
            rows.append({"window": window, "variant": variant, **_stats(trades_all, portfolio)})
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "smc_expanded_backtests_2026-08-18_results.csv", index=False)
    manifest = {"symbols": SYMBOLS, "timeframe": "15min", "source": "Alpaca IEX",
                "capital": CAPITAL, "slippage_bps": SLIPPAGE_BPS,
                "variants": VARIANTS, "windows": list(_windows(last)),
                "coverage": "partial_15m; no 1d/4h/5m MTF validation"}
    (OUT / "smc_expanded_backtests_2026-08-18_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"rows={len(result)}")


if __name__ == "__main__":
    main()
