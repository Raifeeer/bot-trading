"""Backtests de Volume Profile integrado sobre DayBreakout live.

Usa barras 15m reales cacheadas de Alpaca IEX. La estrategia es una proxy de
exposición al subyacente: no modela P&L de opciones. Todos los perfiles se
construyen con sesiones cerradas anteriores a la barra de decisión.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("/home/ubuntu")
HISTORY = ROOT / "backtests/volume_profile_history"
OUT = ROOT / "backtests"
CAPITAL = 100_000.0
SYMBOLS = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
RTH_START = time(9, 30)
RTH_END = time(16, 0)
ENTRY_START = time(10, 0)
ENTRY_END = time(15, 30)
DONCHIAN_PERIOD = 10
ATR_PERIOD = 14
ATR_STOP_MULT = 2.5
HOLD_MAX_BARS = 20
COMMISSION_USD = 0.0
SLIPPAGE_BPS = 5.0


@dataclass(frozen=True)
class Profile:
    poc: float
    vah: float
    val: float
    hvn: tuple[float, ...]
    lvn: tuple[float, ...]
    total_volume: float


def _load(symbol: str) -> pd.DataFrame:
    frame = pd.read_pickle(HISTORY / f"{symbol}.pkl")
    frame = frame.copy()
    frame.index = pd.to_datetime(frame.index, utc=True).tz_convert("America/New_York")
    frame = frame.sort_index()
    frame = frame.between_time(RTH_START, RTH_END, inclusive="left")
    return frame.dropna(subset=["open", "high", "low", "close", "volume"])


def _atr(frame: pd.DataFrame) -> pd.Series:
    prev_close = frame["close"].shift(1)
    tr = pd.concat(
        [frame["high"] - frame["low"],
         (frame["high"] - prev_close).abs(),
         (frame["low"] - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(ATR_PERIOD).mean()


def _profile(frame: pd.DataFrame, bins: int, value_area_pct: float) -> Profile | None:
    if frame.empty:
        return None
    low = float(frame["low"].min())
    high = float(frame["high"].max())
    total_volume = float(frame["volume"].sum())
    if not np.isfinite(low) or not np.isfinite(high) or high <= low or total_volume <= 0:
        return None
    edges = np.linspace(low, high, bins + 1)
    typical = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    idx = np.clip(np.searchsorted(edges, typical, side="right") - 1, 0, bins - 1)
    volumes = np.bincount(idx, weights=frame["volume"], minlength=bins).astype(float)
    centers = (edges[:-1] + edges[1:]) / 2.0
    poc_idx = int(np.argmax(volumes))
    selected = {poc_idx}
    target = total_volume * value_area_pct
    while volumes[list(selected)].sum() < target and len(selected) < bins:
        left = min(selected) - 1
        right = max(selected) + 1
        left_volume = volumes[left] if left >= 0 else -1.0
        right_volume = volumes[right] if right < bins else -1.0
        if right_volume > left_volume:
            selected.add(right)
        elif left >= 0:
            selected.add(left)
        elif right < bins:
            selected.add(right)
        else:
            break
    value_indices = sorted(selected)
    threshold_hvn = float(np.percentile(volumes[volumes > 0], 70)) if np.any(volumes > 0) else 0.0
    threshold_lvn = float(np.percentile(volumes[volumes > 0], 30)) if np.any(volumes > 0) else 0.0
    hvn = tuple(float(centers[i]) for i in range(1, bins - 1)
                if volumes[i] >= volumes[i - 1] and volumes[i] >= volumes[i + 1]
                and volumes[i] >= threshold_hvn)
    lvn = tuple(float(centers[i]) for i in range(1, bins - 1)
                if volumes[i] <= volumes[i - 1] and volumes[i] <= volumes[i + 1]
                and volumes[i] <= threshold_lvn)
    return Profile(float(centers[poc_idx]), float(centers[value_indices[-1]]),
                   float(centers[value_indices[0]]), hvn, lvn, total_volume)


def _profiles(frame: pd.DataFrame, bins: int, value_area_pct: float,
              lookback_sessions: int) -> dict[pd.Timestamp, Profile]:
    days = sorted(pd.Index(frame.index.date).unique())
    by_day = {day: frame[frame.index.date == day] for day in days}
    output: dict[pd.Timestamp, Profile] = {}
    for i, day in enumerate(days):
        prior_days = days[max(0, i - lookback_sessions):i]
        if not prior_days:
            continue
        history = pd.concat([by_day[d] for d in prior_days], axis=0)
        profile = _profile(history, bins, value_area_pct)
        if profile is not None:
            output[pd.Timestamp(day)] = profile
    return output


def _season_windows(last_date: pd.Timestamp) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    end = last_date.normalize() + pd.Timedelta(days=1)
    return {
        "selloff_spring_2026": (pd.Timestamp("2026-03-01", tz=end.tz),
                                pd.Timestamp("2026-04-30", tz=end.tz) + pd.Timedelta(days=1)),
        "recovery_may_2026": (pd.Timestamp("2026-05-01", tz=end.tz),
                              pd.Timestamp("2026-05-31", tz=end.tz) + pd.Timedelta(days=1)),
        "summer_2026": (pd.Timestamp("2026-06-01", tz=end.tz), end),
        "latest_30d": (end - pd.Timedelta(days=30), end),
        "full_recent": (end - pd.Timedelta(days=365), end),
    }


def _simulate(frame: pd.DataFrame, profiles: dict[pd.Timestamp, Profile],
              variant: str, capital: float, start: pd.Timestamp,
              end: pd.Timestamp) -> tuple[list[dict[str, object]], pd.Series]:
    data = frame[(frame.index >= start) & (frame.index < end)].copy()
    if data.empty:
        return [], pd.Series(dtype=float)
    data["atr"] = _atr(data)
    data["donch_hi"] = data["high"].shift(1).rolling(DONCHIAN_PERIOD).max()
    data["donch_lo"] = data["low"].shift(1).rolling(DONCHIAN_PERIOD).min()
    data["volume_mean"] = data["volume"].rolling(20).mean()
    allocation = capital / len(SYMBOLS)
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
    for ts, row in data.iterrows():
        if last_day is not None and ts.date() != last_day:
            curve.append((pd.Timestamp(last_day, tz=ts.tz), last_mark))
        day_key = pd.Timestamp(ts.date())
        profile = profiles.get(day_key)
        close = float(row["close"])
        if shares > 0:
            bars_held += 1
            stop_hit = float(row["low"]) <= float(stop_price)
            fallback = close < float(row["donch_lo"]) if pd.notna(row["donch_lo"]) else False
            max_hold = bars_held >= HOLD_MAX_BARS
            if stop_hit or fallback or max_hold:
                exit_price = float(stop_price) if stop_hit else close
                exit_price *= 1.0 - SLIPPAGE_BPS / 10_000.0
                pnl = shares * (exit_price - float(entry_price)) - COMMISSION_USD
                cash += shares * exit_price - COMMISSION_USD
                trades.append({"entry_ts": entry_ts, "exit_ts": ts,
                               "entry_price": entry_price, "exit_price": exit_price,
                               "pnl": pnl, "reason": "stop" if stop_hit else
                               ("fallback" if fallback else "max_hold"),
                               "bars": bars_held})
                shares = 0.0
                entry_price = None
                stop_price = None
                entry_ts = None
                bars_held = 0
        if shares == 0 and profile is not None and ENTRY_START <= ts.time() < ENTRY_END:
            breakout = pd.notna(row["donch_hi"]) and close > float(row["donch_hi"])
            if breakout:
                if variant == "baseline":
                    allowed = True
                elif variant == "vah_filter":
                    allowed = close > profile.vah
                elif variant == "poc_filter":
                    allowed = close > profile.poc
                elif variant == "acceptance":
                    allowed = close > profile.vah and row["volume"] >= row["volume_mean"]
                elif variant == "vah_poc":
                    allowed = close > profile.vah and close > profile.poc
                else:
                    raise ValueError(f"Variante desconocida: {variant}")
                if allowed and pd.notna(row["atr"]) and float(row["atr"]) > 0:
                    entry_price = close * (1.0 + SLIPPAGE_BPS / 10_000.0)
                    shares = (allocation - COMMISSION_USD) / entry_price
                    cash -= shares * entry_price + COMMISSION_USD
                    stop_price = max(0.01, close - ATR_STOP_MULT * float(row["atr"]))
                    entry_ts = ts
                    bars_held = 0
        last_day = ts.date()
        last_mark = cash + shares * close
    if last_day is not None:
        curve.append((pd.Timestamp(last_day, tz=data.index.tz), last_mark))
    if shares > 0:
        ts = data.index[-1]
        exit_price = float(data.iloc[-1]["close"]) * (1.0 - SLIPPAGE_BPS / 10_000.0)
        pnl = shares * (exit_price - float(entry_price)) - COMMISSION_USD
        cash += shares * exit_price - COMMISSION_USD
        trades.append({"entry_ts": entry_ts, "exit_ts": ts,
                       "entry_price": entry_price, "exit_price": exit_price,
                       "pnl": pnl, "reason": "window_end", "bars": bars_held})
        curve[-1] = (ts, cash)
    return trades, pd.Series(dict(curve)).sort_index()


def _stats(trades: list[dict[str, object]], curve: pd.Series, capital: float) -> dict[str, float]:
    if curve.empty:
        return {"return_pct": 0.0, "drawdown_pct": 0.0, "trades": 0,
                "win_rate_pct": 0.0, "profit_factor": 0.0}
    peak = curve.cummax()
    drawdown = curve / peak - 1.0
    pnl = pd.Series([float(t["pnl"]) for t in trades]) if trades else pd.Series(dtype=float)
    gains = pnl[pnl > 0].sum()
    losses = -pnl[pnl < 0].sum()
    return {"return_pct": float((curve.iloc[-1] / capital - 1.0) * 100.0),
            "drawdown_pct": float(drawdown.min() * 100.0),
            "trades": float(len(trades)),
            "win_rate_pct": float((pnl > 0).mean() * 100.0) if len(pnl) else 0.0,
            "profit_factor": float(gains / losses) if losses > 0 else (float("inf") if gains > 0 else 0.0)}


def main() -> None:
    frames = {symbol: _load(symbol) for symbol in SYMBOLS}
    last = max(frame.index.max() for frame in frames.values())
    windows = _season_windows(last)
    rows: list[dict[str, object]] = []
    variants = ["baseline", "vah_filter", "poc_filter", "acceptance", "vah_poc"]
    for bins in (24, 48, 96):
        for value_area_pct in (0.68, 0.70, 0.80):
            for lookback in (1, 3, 5):
                profiles = {symbol: _profiles(frame, bins, value_area_pct, lookback)
                            for symbol, frame in frames.items()}
                for window, (start, end) in windows.items():
                    for variant in variants:
                        all_trades: list[dict[str, object]] = []
                        curves = []
                        for symbol, frame in frames.items():
                            trades, curve = _simulate(frame, profiles[symbol], variant,
                                                      CAPITAL, start, end)
                            all_trades.extend({**trade, "symbol": symbol} for trade in trades)
                            if not curve.empty:
                                curves.append(curve.rename(symbol))
                        if curves:
                            portfolio = (pd.concat(curves, axis=1).ffill()
                                         .fillna(CAPITAL / len(SYMBOLS)).sum(axis=1))
                        else:
                            portfolio = pd.Series(dtype=float)
                        stat = _stats(all_trades, portfolio, CAPITAL)
                        rows.append({"window": window, "variant": variant,
                                     "bins": bins, "value_area_pct": value_area_pct,
                                     "lookback_sessions": lookback, **stat})
    result = pd.DataFrame(rows)
    result.to_csv(OUT / "volume_profile_backtests_2026-08-18_results.csv", index=False)
    manifest = {"symbols": SYMBOLS, "rows": len(result), "timeframe": "15min",
                "source": "Alpaca IEX historical bars", "capital": CAPITAL,
                "slippage_bps": SLIPPAGE_BPS, "commission_usd": COMMISSION_USD,
                "variants": variants, "bins": [24, 48, 96],
                "value_area_pct": [0.68, 0.70, 0.80],
                "lookback_sessions": [1, 3, 5], "windows": list(windows)}
    (OUT / "volume_profile_backtests_2026-08-18_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"rows={len(result)}")


if __name__ == "__main__":
    main()
