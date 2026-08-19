"""Features deterministas de SMC ampliado para investigación.

Este módulo es deliberadamente puro y no envía órdenes. Todas las funciones
usan únicamente el DataFrame recibido y devuelven evidencia OHLCV, no claims
sobre órdenes institucionales reales.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class FVG:
    direction: str
    top: float
    bottom: float
    created_idx: int
    filled: bool


@dataclass(frozen=True)
class Zone:
    direction: str
    top: float
    bottom: float
    created_idx: int
    kind: str
    invalidated: bool


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat(
        [frame["high"] - frame["low"],
         (frame["high"] - prev).abs(),
         (frame["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def confirmed_swings(frame: pd.DataFrame, order: int = 3) -> list[tuple[int, float, bool]]:
    """Return confirmed pivots; the last `order` bars never form a pivot."""
    if len(frame) < 2 * order + 3:
        return []
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    last_confirmed = len(frame) - order - 1
    swings: list[tuple[int, float, bool]] = []
    for i in range(order, last_confirmed + 1):
        if highs[i] >= max(highs[i - order:i + order + 1]):
            swings.append((i, float(highs[i]), True))
        elif lows[i] <= min(lows[i - order:i + order + 1]):
            swings.append((i, float(lows[i]), False))
    return swings


def _structure(frame: pd.DataFrame, order: int = 3) -> tuple[str, list[tuple[int, float, bool]]]:
    swings = confirmed_swings(frame, order)
    highs = [s for s in swings if s[2]][-3:]
    lows = [s for s in swings if not s[2]][-3:]
    if len(highs) >= 2 and len(lows) >= 2:
        if highs[-1][1] > highs[-2][1] and lows[-1][1] > lows[-2][1]:
            return "bull", swings
        if highs[-1][1] < highs[-2][1] and lows[-1][1] < lows[-2][1]:
            return "bear", swings
    return "range", swings


def fair_value_gaps(frame: pd.DataFrame, atr_period: int = 14,
                    min_atr_fraction: float = 0.10,
                    max_age_bars: int = 20) -> list[FVG]:
    """Detect three-candle FVGs and mark fill using only bars up to now."""
    atr = _atr(frame, atr_period)
    last = len(frame) - 1
    output: list[FVG] = []
    for i in range(2, last + 1):
        gap = None
        if frame.iloc[i]["low"] > frame.iloc[i - 2]["high"]:
            gap = ("bull", float(frame.iloc[i]["low"]), float(frame.iloc[i - 2]["high"]))
        elif frame.iloc[i]["high"] < frame.iloc[i - 2]["low"]:
            gap = ("bear", float(frame.iloc[i - 2]["low"]), float(frame.iloc[i]["high"]))
        if gap is None or i < last - max_age_bars:
            continue
        direction, top, bottom = gap
        size = top - bottom
        atr_value = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
        if atr_value <= 0 or size < min_atr_fraction * atr_value:
            continue
        future = frame.iloc[i + 1:last + 1]
        if direction == "bull":
            filled = bool((future["close"] <= bottom).any())
        else:
            filled = bool((future["close"] >= top).any())
        output.append(FVG(direction, top, bottom, i, filled))
    return output


def order_blocks(frame: pd.DataFrame, order: int = 3, atr_period: int = 14,
                 displacement_atr: float = 1.0, max_age_bars: int = 40) -> list[Zone]:
    """Find last opposite candle before a displacement across a swing."""
    atr = _atr(frame, atr_period)
    _, swings = _structure(frame, order)
    last = len(frame) - 1
    zones: list[Zone] = []
    for i in range(max(1, last - max_age_bars), last - 1):
        if pd.isna(atr.iloc[i + 1]):
            continue
        body = abs(float(frame.iloc[i + 1]["close"] - frame.iloc[i + 1]["open"]))
        if body < displacement_atr * float(atr.iloc[i + 1]):
            continue
        bull = frame.iloc[i]["close"] < frame.iloc[i]["open"] and frame.iloc[i + 1]["close"] > frame.iloc[i + 1]["open"]
        bear = frame.iloc[i]["close"] > frame.iloc[i]["open"] and frame.iloc[i + 1]["close"] < frame.iloc[i + 1]["open"]
        if not (bull or bear):
            continue
        prior = [s for s in swings if s[0] < i and s[2] == bull]
        if not prior:
            continue
        broken = any(float(frame.iloc[i + 1]["close"]) > s[1] for s in prior) if bull else any(float(frame.iloc[i + 1]["close"]) < s[1] for s in prior)
        if not broken:
            continue
        if bull:
            top = float(frame.iloc[i]["open"])
            bottom = float(frame.iloc[i]["low"])
            invalidated = bool(frame.iloc[last]["close"] < bottom)
            zones.append(Zone("bull", top, bottom, i, "order_block", invalidated))
        elif bear:
            top = float(frame.iloc[i]["high"])
            bottom = float(frame.iloc[i]["open"])
            invalidated = bool(frame.iloc[last]["close"] > top)
            zones.append(Zone("bear", top, bottom, i, "order_block", invalidated))
    return zones[-3:]


def snapshot(frame: pd.DataFrame, order: int = 3) -> dict[str, object]:
    """Return the latest confirmed SMC features for a closed-bar frame."""
    if len(frame) < 60:
        return {"bias": "neutral", "bos": None, "mss": False,
                "fvg_bull": False, "ob_bull": False, "sweep_bull": False,
                "coverage": False}
    bias, swings = _structure(frame, order)
    atr = _atr(frame)
    last = frame.iloc[-1]
    last_atr = float(atr.iloc[-1]) if pd.notna(atr.iloc[-1]) else 0.0
    bos = None
    mss = False
    recent_swings = swings[-8:]
    for _idx, price, is_high in reversed(recent_swings):
        if is_high and float(last["close"]) > price:
            bos = "bull"
            break
        if not is_high and float(last["close"]) < price:
            bos = "bear"
            break
    body = abs(float(last["close"] - last["open"]))
    if bos is not None and last_atr > 0:
        mss = body >= 1.5 * last_atr
    fvgs = fair_value_gaps(frame)
    obs = order_blocks(frame, order)
    bull_fvg = any(f.direction == "bull" and not f.filled for f in fvgs)
    bull_ob = any(z.direction == "bull" and not z.invalidated for z in obs)
    last_low = next((price for _, price, high in reversed(recent_swings) if not high), None)
    last_high = next((price for _, price, high in reversed(recent_swings) if high), None)
    sweep_bull = bool(last_low is not None and float(last["low"]) < last_low
                     and float(last["close"]) > last_low)
    sweep_bear = bool(last_high is not None and float(last["high"]) > last_high
                     and float(last["close"]) < last_high)
    return {"bias": bias, "bos": bos, "mss": mss,
            "fvg_bull": bull_fvg, "fvg_bear": any(f.direction == "bear" and not f.filled for f in fvgs),
            "ob_bull": bull_ob, "ob_bear": any(z.direction == "bear" and not z.invalidated for z in obs),
            "sweep_bull": sweep_bull, "sweep_bear": sweep_bear,
            "coverage": True}
