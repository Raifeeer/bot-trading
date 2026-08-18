"""Capa pura de setups direccionales para Polaris.

El módulo convierte patrones visuales del PDF de setups en observaciones
serializables. No consulta brokers, no muta estado de ejecución y no envía
órdenes. La salida está diseñada para shadow/PAPER y para backtests con barras
cerradas.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd


SETUP_NAMES = (
    "key_level",
    "break_and_retest",
    "order_block",
    "bos",
    "choch",
    "liquidity_sweep",
    "ema_cross",
    "ema_cloud",
    "vwap",
    "volume_proxy",
    "fibonacci_ote",
    "trendline_channel",
)

STRUCTURAL_SETUPS = frozenset(
    {"key_level", "break_and_retest", "order_block", "bos", "choch", "liquidity_sweep"}
)


@dataclass(frozen=True)
class SetupObservation:
    """Observación de un setup en la última barra cerrada disponible."""

    symbol: str
    setup: str
    direction: str
    status: str
    score: float
    decision_ts: str
    evidence: dict[str, Any]
    invalidation: dict[str, Any]
    timeframes: dict[str, str]
    source_version: str = "setup-confluence-v1"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(df: pd.DataFrame | None) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    mapping = {str(c).lower(): c for c in df.columns}
    required = {"open", "high", "low", "close"}
    if not required.issubset(mapping):
        return pd.DataFrame()
    out = df.rename(
        columns={mapping[k]: k.title() for k in mapping if k in {"open", "high", "low", "close", "volume"}}
    ).copy()
    if "Volume" not in out:
        out["Volume"] = 0.0
    return out[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna()


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    if len(df) < 2:
        return 0.0
    high, low, close = df["High"], df["Low"], df["Close"]
    tr = pd.concat(
        [high - low, (high - close.shift()).abs(), (low - close.shift()).abs()], axis=1
    ).max(axis=1)
    value = tr.rolling(period, min_periods=2).mean().iloc[-1]
    return float(value) if pd.notna(value) else float(tr.iloc[-1])


def _obs(
    symbol: str,
    setup: str,
    direction: str,
    status: str,
    score: float,
    evidence: dict[str, Any],
    invalidation: dict[str, Any] | None = None,
    timeframes: dict[str, str] | None = None,
    decision_ts: str | None = None,
) -> SetupObservation:
    return SetupObservation(
        symbol=symbol,
        setup=setup,
        direction=direction if direction in {"bull", "bear", "neutral"} else "neutral",
        status=status,
        score=round(float(max(0.0, min(1.0, score))), 4),
        decision_ts=decision_ts or datetime.now(timezone.utc).isoformat(),
        evidence=evidence,
        invalidation=invalidation or {},
        timeframes=timeframes or {},
    )


def _empty(symbol: str, setup: str, reason: str, **kwargs: Any) -> SetupObservation:
    return _obs(symbol, setup, "neutral", "neutral", 0.0, {"reason": reason}, **kwargs)


def _confirmed_swings(df: pd.DataFrame, order: int = 2) -> list[tuple[int, float, bool]]:
    if len(df) < 2 * order + 3:
        return []
    highs, lows = df["High"].to_numpy(), df["Low"].to_numpy()
    result: list[tuple[int, float, bool]] = []
    for i in range(order, len(df) - order):
        if highs[i] >= max(highs[i - order : i + order + 1]):
            result.append((i, float(highs[i]), True))
        elif lows[i] <= min(lows[i - order : i + order + 1]):
            result.append((i, float(lows[i]), False))
    return result


def _key_level(symbol: str, df: pd.DataFrame, decision_ts: str) -> SetupObservation:
    if len(df) < 12:
        return _empty(symbol, "key_level", "insufficient_history", decision_ts=decision_ts)
    atr = _atr(df)
    close = float(df["Close"].iloc[-1])
    high = float(df["High"].iloc[-1])
    low = float(df["Low"].iloc[-1])
    prev_high = float(df["High"].iloc[-2])
    prev_low = float(df["Low"].iloc[-2])
    rolling_high = float(df["High"].iloc[:-1].tail(20).max())
    rolling_low = float(df["Low"].iloc[:-1].tail(20).min())
    tol = max(atr * 0.15, close * 0.0005)
    bull_break = close > max(prev_high, rolling_high) + tol
    bear_break = close < min(prev_low, rolling_low) - tol
    bull_reclaim = low < min(prev_low, rolling_low) - tol and close > min(prev_low, rolling_low) + tol
    bear_reclaim = high > max(prev_high, rolling_high) + tol and close < max(prev_high, rolling_high) - tol
    if bull_break or bull_reclaim:
        direction = "bull"
        status = "confirmed" if bull_break else "candidate"
        reason = "cierre sobre resistencia previa o sweep SSL con reclaim"
        level = max(prev_high, rolling_high)
    elif bear_break or bear_reclaim:
        direction = "bear"
        status = "confirmed" if bear_break else "candidate"
        reason = "cierre bajo soporte previo o sweep BSL con reclaim"
        level = min(prev_low, rolling_low)
    else:
        direction = "neutral"
        status = "context"
        reason = "PDH/PDL congelado; falta reacción cerrada"
        level = prev_high if abs(close - prev_high) <= abs(close - prev_low) else prev_low
    return _obs(
        symbol,
        "key_level",
        direction,
        status,
        0.65 if direction != "neutral" else 0.0,
        {
            "prior_high": prev_high,
            "prior_low": prev_low,
            "rolling_high": rolling_high,
            "rolling_low": rolling_low,
            "bull_break": bull_break,
            "bear_break": bear_break,
            "bull_reclaim": bull_reclaim,
            "bear_reclaim": bear_reclaim,
            "tolerance": tol,
        },
        {"level": level, "reason": reason},
        decision_ts=decision_ts,
    )


def _break_retest(symbol: str, df: pd.DataFrame, decision_ts: str) -> SetupObservation:
    if len(df) < 30:
        return _empty(symbol, "break_and_retest", "insufficient_history", decision_ts=decision_ts)
    atr = _atr(df)
    tol = max(atr * 0.20, float(df.Close.iloc[-1]) * 0.0005)
    lookback, max_bars = 20, 8
    start = max(lookback + 1, len(df) - max_bars - 5)
    candidates: list[tuple[int, float, str]] = []
    for i in range(start, len(df) - 1):
        prior_high = float(df.High.iloc[i - lookback : i].max())
        prior_low = float(df.Low.iloc[i - lookback : i].min())
        if float(df.Close.iloc[i]) > prior_high + tol:
            candidates.append((i, prior_high, "bull"))
        elif float(df.Close.iloc[i]) < prior_low - tol:
            candidates.append((i, prior_low, "bear"))
    if not candidates:
        return _empty(symbol, "break_and_retest", "no_confirmed_break", decision_ts=decision_ts)
    i, level, direction = candidates[-1]
    retest = None
    end = min(len(df), i + 1 + max_bars)
    for j in range(i + 1, end):
        row = df.iloc[j]
        touched = float(row.Low) <= level + tol if direction == "bull" else float(row.High) >= level - tol
        held = float(row.Close) >= level if direction == "bull" else float(row.Close) <= level
        if touched and held:
            retest = j
    if retest is None:
        if len(df) - i > max_bars:
            status = "expired"
        else:
            status = "broken"
        return _obs(symbol, "break_and_retest", "neutral", status, 0.25, {"level": level, "break_idx": i, "break_direction": direction, "bars_since_break": len(df) - 1 - i}, {"level": level, "reason": "no_retest"}, decision_ts=decision_ts)
    last = df.iloc[-1]
    held = float(last.Close) >= level if direction == "bull" else float(last.Close) <= level
    failed = float(last.Close) < level - tol if direction == "bull" else float(last.Close) > level + tol
    if failed:
        return _obs(symbol, "break_and_retest", "neutral", "failed", 0.0, {"level": level, "break_idx": i, "retest_idx": retest}, {"level": level, "reason": "close_back_inside_old_range"}, decision_ts=decision_ts)
    if not held:
        return _obs(symbol, "break_and_retest", "neutral", "retest", 0.35, {"level": level, "break_idx": i, "retest_idx": retest}, {"level": level, "reason": "no_hold"}, decision_ts=decision_ts)
    displacement = abs(float(last.Close) - level) / max(atr, 1e-9)
    return _obs(symbol, "break_and_retest", direction, "confirmed", min(1.0, 0.55 + displacement * 0.1), {"level": level, "break_idx": i, "retest_idx": retest, "bars_since_break": len(df) - 1 - i, "displacement_atr": displacement}, {"level": level, "reason": "close_back_through_level"}, decision_ts=decision_ts)


def _order_block(symbol: str, df: pd.DataFrame, decision_ts: str) -> SetupObservation:
    if len(df) < 25:
        return _empty(symbol, "order_block", "insufficient_history", decision_ts=decision_ts)
    atr = _atr(df)
    last = df.iloc[-1]
    for i in range(len(df) - 4, max(1, len(df) - 25), -1):
        row, nxt = df.iloc[i], df.iloc[i + 1]
        if row.Close < row.Open and nxt.Close > row.High + atr * 0.5:
            bottom, top = float(row.Low), float(row.Open)
            if bottom - atr * 0.15 <= float(last.Close) <= top + atr * 0.15:
                return _obs(symbol, "order_block", "bull", "candidate", 0.65, {"zone": "demand", "top": top, "bottom": bottom, "origin_idx": i, "displacement_atr": abs(float(nxt.Close) - float(row.High)) / max(atr, 1e-9)}, {"level": bottom, "reason": "close_below_demand"}, decision_ts=decision_ts)
        if row.Close > row.Open and nxt.Close < row.Low - atr * 0.5:
            bottom, top = float(row.Open), float(row.High)
            if bottom - atr * 0.15 <= float(last.Close) <= top + atr * 0.15:
                return _obs(symbol, "order_block", "bear", "candidate", 0.65, {"zone": "supply", "top": top, "bottom": bottom, "origin_idx": i, "displacement_atr": abs(float(row.Low) - float(nxt.Close)) / max(atr, 1e-9)}, {"level": top, "reason": "close_above_supply"}, decision_ts=decision_ts)
    return _empty(symbol, "order_block", "no_recent_mitigated_zone", decision_ts=decision_ts)


def _structure(symbol: str, df: pd.DataFrame, setup: str, decision_ts: str) -> SetupObservation:
    swings = _confirmed_swings(df, order=2)
    if len(swings) < 4:
        return _empty(symbol, setup, "insufficient_confirmed_swings", decision_ts=decision_ts)
    last_close = float(df.Close.iloc[-1])
    highs = [s for s in swings if s[2]]
    lows = [s for s in swings if not s[2]]
    if not highs or not lows:
        return _empty(symbol, setup, "missing_swing_side", decision_ts=decision_ts)
    last_high, last_low = highs[-1], lows[-1]
    atr = _atr(df)
    buffer = max(atr * 0.10, last_close * 0.0003)
    if setup == "bos":
        if last_close > last_high[1] + buffer:
            return _obs(symbol, setup, "bull", "confirmed", 0.70, {"broken_level": last_high[1], "swing_idx": last_high[0], "close": last_close}, {"level": last_high[1], "reason": "close_below_broken_swing"}, decision_ts=decision_ts)
        if last_close < last_low[1] - buffer:
            return _obs(symbol, setup, "bear", "confirmed", 0.70, {"broken_level": last_low[1], "swing_idx": last_low[0], "close": last_close}, {"level": last_low[1], "reason": "close_above_broken_swing"}, decision_ts=decision_ts)
        return _empty(symbol, setup, "no_confirmed_break", decision_ts=decision_ts)
    prior_highs, prior_lows = highs[-3:-1], lows[-3:-1]
    if len(prior_highs) < 2 or len(prior_lows) < 2:
        return _empty(symbol, setup, "insufficient_structure", decision_ts=decision_ts)
    trend_bull = prior_highs[-1][1] > prior_highs[-2][1] and prior_lows[-1][1] > prior_lows[-2][1]
    trend_bear = prior_highs[-1][1] < prior_highs[-2][1] and prior_lows[-1][1] < prior_lows[-2][1]
    if trend_bull and last_close < prior_lows[-1][1] - buffer:
        return _obs(symbol, setup, "bear", "candidate", 0.55, {"prior_trend": "bull", "broken_level": prior_lows[-1][1], "close": last_close}, {"level": prior_lows[-1][1], "reason": "close_back_above_level"}, decision_ts=decision_ts)
    if trend_bear and last_close > prior_highs[-1][1] + buffer:
        return _obs(symbol, setup, "bull", "candidate", 0.55, {"prior_trend": "bear", "broken_level": prior_highs[-1][1], "close": last_close}, {"level": prior_highs[-1][1], "reason": "close_back_below_level"}, decision_ts=decision_ts)
    return _empty(symbol, setup, "no_character_change", decision_ts=decision_ts)


def _liquidity_sweep(symbol: str, df: pd.DataFrame, decision_ts: str) -> SetupObservation:
    if len(df) < 25:
        return _empty(symbol, "liquidity_sweep", "insufficient_history", decision_ts=decision_ts)
    atr = _atr(df)
    prior_high = float(df.High.iloc[:-1].tail(20).max())
    prior_low = float(df.Low.iloc[:-1].tail(20).min())
    last = df.iloc[-1]
    buffer = max(atr * 0.10, float(last.Close) * 0.0003)
    if float(last.Low) < prior_low - buffer and float(last.Close) > prior_low:
        return _obs(symbol, "liquidity_sweep", "bull", "confirmed", 0.65, {"side": "SSL", "swept_level": prior_low, "low": float(last.Low), "close": float(last.Close)}, {"level": prior_low, "reason": "close_below_reclaimed_ssl"}, decision_ts=decision_ts)
    if float(last.High) > prior_high + buffer and float(last.Close) < prior_high:
        return _obs(symbol, "liquidity_sweep", "bear", "confirmed", 0.65, {"side": "BSL", "swept_level": prior_high, "high": float(last.High), "close": float(last.Close)}, {"level": prior_high, "reason": "close_above_reclaimed_bsl"}, decision_ts=decision_ts)
    return _empty(symbol, "liquidity_sweep", "no_reclaiming_sweep", decision_ts=decision_ts)


def _trend_indicators(symbol: str, df: pd.DataFrame, decision_ts: str) -> list[SetupObservation]:
    if len(df) < 55:
        return [_empty(symbol, setup, "insufficient_history", decision_ts=decision_ts) for setup in ("ema_cross", "ema_cloud", "vwap", "volume_proxy", "fibonacci_ote", "trendline_channel")]
    close, high, low, volume = df.Close, df.High, df.Low, df.Volume
    ema9, ema21, ema50 = close.ewm(span=9, adjust=False).mean(), close.ewm(span=21, adjust=False).mean(), close.ewm(span=50, adjust=False).mean()
    atr = _atr(df)
    last_close = float(close.iloc[-1])
    slope9 = float(ema9.iloc[-1] - ema9.iloc[-4])
    slope21 = float(ema21.iloc[-1] - ema21.iloc[-4])
    cross_dir = "bull" if ema9.iloc[-1] > ema21.iloc[-1] and slope9 > 0 and slope21 > 0 else "bear" if ema9.iloc[-1] < ema21.iloc[-1] and slope9 < 0 and slope21 < 0 else "neutral"
    ema_cross = _obs(symbol, "ema_cross", cross_dir, "candidate" if cross_dir != "neutral" else "neutral", 0.45 if cross_dir != "neutral" else 0.0, {"ema9": float(ema9.iloc[-1]), "ema21": float(ema21.iloc[-1]), "slope9": slope9, "slope21": slope21}, {"level": float(ema21.iloc[-1]), "reason": "cross_lost"}, decision_ts=decision_ts)
    cloud_dir = "bull" if last_close > ema9.iloc[-1] > ema21.iloc[-1] > ema50.iloc[-1] else "bear" if last_close < ema9.iloc[-1] < ema21.iloc[-1] < ema50.iloc[-1] else "neutral"
    ema_cloud = _obs(symbol, "ema_cloud", cloud_dir, "candidate" if cloud_dir != "neutral" else "neutral", 0.45 if cloud_dir != "neutral" else 0.0, {"ema9": float(ema9.iloc[-1]), "ema21": float(ema21.iloc[-1]), "ema50": float(ema50.iloc[-1]), "close": last_close}, {"level": float(ema50.iloc[-1]), "reason": "cloud_alignment_lost"}, decision_ts=decision_ts)
    typical = (high + low + close) / 3.0
    if isinstance(df.index, pd.DatetimeIndex) and len(df.index) > 1 and df.index[-1].date() == df.index[0].date():
        vwap = (typical * volume).cumsum() / volume.replace(0, np.nan).cumsum()
    else:
        vwap = (typical * volume).rolling(20, min_periods=5).sum() / volume.replace(0, np.nan).rolling(20, min_periods=5).sum()
    vwap_value = float(vwap.iloc[-1]) if pd.notna(vwap.iloc[-1]) else float(typical.iloc[-1])
    vwap_dir = "bull" if last_close > vwap_value + max(atr * 0.1, 1e-9) else "bear" if last_close < vwap_value - max(atr * 0.1, 1e-9) else "neutral"
    vwap_obs = _obs(symbol, "vwap", vwap_dir, "candidate" if vwap_dir != "neutral" else "neutral", 0.35 if vwap_dir != "neutral" else 0.0, {"vwap": vwap_value, "close": last_close, "volume_available": bool(volume.sum() > 0)}, {"level": vwap_value, "reason": "close_crossed_vwap"}, decision_ts=decision_ts)
    avg_vol = float(volume.rolling(30, min_periods=5).mean().iloc[-1]) if volume.sum() > 0 else 0.0
    clv = ((close - low) - (high - close)) / (high - low).replace(0, np.nan)
    proxy = float((clv * volume).iloc[-1] / max(avg_vol, 1e-9)) if avg_vol > 0 else 0.0
    vol_dir = "bull" if proxy > 0.35 else "bear" if proxy < -0.35 else "neutral"
    volume_obs = _obs(symbol, "volume_proxy", vol_dir, "confirmation" if vol_dir != "neutral" else "neutral", min(1.0, abs(proxy) / 2), {"clv_volume_ratio": proxy, "avg_volume": avg_vol, "formula": "CLV*Volume / rolling_mean_volume"}, {}, decision_ts=decision_ts)
    prior_high = float(high.iloc[:-1].tail(40).max())
    prior_low = float(low.iloc[:-1].tail(40).min())
    span = max(prior_high - prior_low, 1e-9)
    pos = (last_close - prior_low) / span
    fib_dir = "bull" if 0.50 <= pos <= 0.79 and last_close > ema50.iloc[-1] else "bear" if 0.21 <= pos <= 0.50 and last_close < ema50.iloc[-1] else "neutral"
    fib_obs = _obs(symbol, "fibonacci_ote", fib_dir, "candidate" if fib_dir != "neutral" else "neutral", 0.30 if fib_dir != "neutral" else 0.0, {"swing_high": prior_high, "swing_low": prior_low, "position": pos, "zone": "discount" if pos < 0.5 else "premium"}, {"level": prior_low if fib_dir == "bull" else prior_high, "reason": "swing_invalidated"}, decision_ts=decision_ts)
    x = np.arange(min(20, len(close)))
    y = close.tail(len(x)).to_numpy(dtype=float)
    slope = float(np.polyfit(x, y, 1)[0]) if len(x) >= 3 else 0.0
    norm_slope = slope / max(atr, 1e-9)
    trend_dir = "bull" if norm_slope > 0.08 else "bear" if norm_slope < -0.08 else "neutral"
    trend_obs = _obs(symbol, "trendline_channel", trend_dir, "context" if trend_dir != "neutral" else "neutral", min(1.0, abs(norm_slope) / 0.5), {"slope_per_bar": slope, "slope_atr_normalized": norm_slope, "window": len(x)}, {}, decision_ts=decision_ts)
    return [ema_cross, ema_cloud, vwap_obs, volume_obs, fib_obs, trend_obs]


def _frame_for(frames: dict[str, pd.DataFrame], names: tuple[str, ...]) -> pd.DataFrame:
    for name in names:
        if name in frames and not frames[name].empty:
            return frames[name]
    return pd.DataFrame()


def analyze_setup_confluence(
    symbol: str,
    frames: dict[str, pd.DataFrame],
    decision_ts: str | None = None,
) -> dict[str, Any]:
    """Evalúa todos los setups disponibles y devuelve una confluencia shadow.

    `frames` puede contener `1d`, `15m`, `5m`, `4h` y `1m`. Se usan solo las
    barras recibidas; el llamador debe suministrar barras cerradas y congelar
    el dataset antes de llamar a esta función.
    """
    decision_ts = decision_ts or datetime.now(timezone.utc).isoformat()
    daily = _norm(_frame_for(frames, ("1d", "daily")))
    intraday = _norm(_frame_for(frames, ("5m", "15m", "4h", "1d")))
    if intraday.empty:
        observations = [_empty(symbol, name, "missing_data", decision_ts=decision_ts).as_dict() for name in SETUP_NAMES]
        return {"symbol": symbol, "direction": "neutral", "status": "no_data", "score": 0.0, "observations": observations, "conflicts": []}
    observations = [
        _key_level(symbol, intraday, decision_ts),
        _break_retest(symbol, intraday, decision_ts),
        _order_block(symbol, intraday, decision_ts),
        _structure(symbol, intraday, "bos", decision_ts),
        _structure(symbol, intraday, "choch", decision_ts),
        _liquidity_sweep(symbol, intraday, decision_ts),
    ]
    observations.extend(_trend_indicators(symbol, intraday, decision_ts))
    bull = sum(o.score for o in observations if o.direction == "bull")
    bear = sum(o.score for o in observations if o.direction == "bear")
    structural_bull = any(o.setup in STRUCTURAL_SETUPS and o.direction == "bull" for o in observations)
    structural_bear = any(o.setup in STRUCTURAL_SETUPS and o.direction == "bear" for o in observations)
    conflicts: list[str] = []
    if structural_bull and structural_bear:
        conflicts.append("structural_direction_conflict")
    if abs(bull - bear) < 0.35 or conflicts:
        direction, score, status = "neutral", 0.0, "conflict" if conflicts else "neutral"
    elif bull > bear and structural_bull:
        direction, score, status = "bull", min(1.0, bull / 3.0), "candidate"
    elif bear > bull and structural_bear:
        direction, score, status = "bear", min(1.0, bear / 3.0), "candidate"
    else:
        direction, score, status = "neutral", 0.0, "no_structure"
    mtf = {"regime": "1d" if not daily.empty else "available", "setup": "15m/5m", "entry": "5m"}
    observations.append(_obs(symbol, "mtf_confluence", direction, status, score, {"bull_score": bull, "bear_score": bear, "structural_bull": structural_bull, "structural_bear": structural_bear, "conflicts": conflicts}, {"reason": "direction_invalidated"}, mtf, decision_ts))
    return {"symbol": symbol, "direction": direction, "status": status, "score": round(float(score), 4), "bull_score": round(float(bull), 4), "bear_score": round(float(bear), 4), "conflicts": conflicts, "observations": [o.as_dict() for o in observations]}
