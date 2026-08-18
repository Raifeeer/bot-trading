"""Objective chart-pattern detectors using confirmed pivots only."""
from __future__ import annotations

from itertools import pairwise

import pandas as pd

Pivot = tuple[int, float, int]


def _atr(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    prev = frame["close"].shift(1)
    tr = pd.concat(
        [frame["high"] - frame["low"],
         (frame["high"] - prev).abs(),
         (frame["low"] - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=period).mean()


def _confirmed_pivots(frame: pd.DataFrame, side: str, left: int = 2,
                      right: int = 2) -> list[Pivot]:
    values = frame[side].to_numpy(dtype=float)
    pivots: list[Pivot] = []
    for confirm_i in range(left + right, len(values)):
        pivot_i = confirm_i - right
        window = values[pivot_i - left:pivot_i + right + 1]
        is_unique = (window == values[pivot_i]).sum() == 1
        if side == "high" and is_unique and values[pivot_i] >= window.max():
            pivots.append((pivot_i, values[pivot_i], confirm_i))
        if side == "low" and is_unique and values[pivot_i] <= window.min():
            pivots.append((pivot_i, values[pivot_i], confirm_i))
    return pivots


def double_bottom(frame: pd.DataFrame, tolerance_atr: float = 1.0) -> pd.Series:
    """Long signal after two confirmed lows and neckline breakout."""
    result = pd.Series(False, index=frame.index)
    atr = _atr(frame)
    lows = _confirmed_pivots(frame, "low")
    highs = _confirmed_pivots(frame, "high")
    for (i1, p1, c1), (i2, p2, c2) in pairwise(lows):
        if not 5 <= i2 - i1 <= 60:
            continue
        local_atr = float(atr.iloc[i2]) if pd.notna(atr.iloc[i2]) else 0.0
        if local_atr <= 0 or abs(p2 - p1) > tolerance_atr * local_atr:
            continue
        valleys = [pivot for pivot in highs if i1 < pivot[0] < i2]
        if not valleys:
            continue
        neckline = max(valleys, key=lambda pivot: pivot[1])
        ready = max(c1, c2, neckline[2]) + 1
        for i in range(ready, len(frame)):
            buffer = 0.1 * float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
            if float(frame["close"].iloc[i]) > neckline[1] + buffer:
                result.iloc[i] = True
                break
    return result


def double_top(frame: pd.DataFrame, tolerance_atr: float = 1.0) -> pd.Series:
    """Short signal after two confirmed highs and neckline breakdown."""
    result = pd.Series(False, index=frame.index)
    atr = _atr(frame)
    highs = _confirmed_pivots(frame, "high")
    lows = _confirmed_pivots(frame, "low")
    for (i1, p1, c1), (i2, p2, c2) in pairwise(highs):
        if not 5 <= i2 - i1 <= 60:
            continue
        local_atr = float(atr.iloc[i2]) if pd.notna(atr.iloc[i2]) else 0.0
        if local_atr <= 0 or abs(p2 - p1) > tolerance_atr * local_atr:
            continue
        necklines = [pivot for pivot in lows if i1 < pivot[0] < i2]
        if not necklines:
            continue
        neckline = min(necklines, key=lambda pivot: pivot[1])
        ready = max(c1, c2, neckline[2]) + 1
        for i in range(ready, len(frame)):
            buffer = 0.1 * float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
            if float(frame["close"].iloc[i]) < neckline[1] - buffer:
                result.iloc[i] = True
                break
    return result


def triangle_breakout(frame: pd.DataFrame) -> pd.Series:
    """Directional breakout after two lower highs and two higher lows."""
    result = pd.Series(0, index=frame.index, dtype=int)
    atr = _atr(frame)
    highs = _confirmed_pivots(frame, "high")
    lows = _confirmed_pivots(frame, "low")
    for i in range(len(frame)):
        hs = [pivot for pivot in highs if pivot[2] < i][-2:]
        ls = [pivot for pivot in lows if pivot[2] < i][-2:]
        if len(hs) < 2 or len(ls) < 2:
            continue
        if not hs[1][1] < hs[0][1] or not ls[1][1] > ls[0][1]:
            continue
        if not max(hs[0][0], ls[0][0]) < min(hs[1][0], ls[1][0]):
            continue
        buffer = 0.1 * float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
        if float(frame["close"].iloc[i]) > hs[1][1] + buffer:
            result.iloc[i] = 1
        elif float(frame["close"].iloc[i]) < ls[1][1] - buffer:
            result.iloc[i] = -1
    return result


def flag_breakout(frame: pd.DataFrame) -> pd.Series:
    """Long/short flag breakout after an impulse and shallow consolidation."""
    result = pd.Series(0, index=frame.index, dtype=int)
    atr = _atr(frame)
    for i in range(25, len(frame)):
        atr_i = float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
        if atr_i <= 0:
            continue
        for pole in (5, 10, 20):
            pole_start = i - pole - 5
            consolidation_start = i - 5
            if pole_start < 0:
                continue
            impulse = float(frame["close"].iloc[i - 5]) - float(frame["close"].iloc[pole_start])
            if abs(impulse) < 2.0 * atr_i:
                continue
            cons = frame.iloc[consolidation_start:i]
            retrace = ((float(cons["close"].iloc[0]) - float(cons["close"].iloc[-1]))
                       if impulse > 0 else
                       (float(cons["close"].iloc[-1]) - float(cons["close"].iloc[0])))
            if retrace > 0.5 * abs(impulse):
                continue
            buffer = 0.1 * atr_i
            if impulse > 0 and float(frame["close"].iloc[i]) > float(cons["high"].max()) + buffer:
                result.iloc[i] = 1
                break
            if impulse < 0 and float(frame["close"].iloc[i]) < float(cons["low"].min()) - buffer:
                result.iloc[i] = -1
                break
    return result


def _head_shoulders(frame: pd.DataFrame, inverse: bool) -> pd.Series:
    result = pd.Series(0, index=frame.index, dtype=int)
    atr = _atr(frame)
    side = "low" if inverse else "high"
    opposite = "high" if inverse else "low"
    shoulders = _confirmed_pivots(frame, side)
    neck_pivots = _confirmed_pivots(frame, opposite)
    for h1_i in range(len(shoulders) - 2):
        first, head, third = shoulders[h1_i:h1_i + 3]
        if not (first[0] < head[0] < third[0]):
            continue
        first_necks = [p for p in neck_pivots if first[0] < p[0] < head[0]]
        second_necks = [p for p in neck_pivots if head[0] < p[0] < third[0]]
        if not first_necks or not second_necks:
            continue
        neck1 = max(first_necks, key=lambda p: p[0])
        neck2 = min(second_necks, key=lambda p: p[0])
        local_atr = float(atr.iloc[third[0]]) if pd.notna(atr.iloc[third[0]]) else 0.0
        if local_atr <= 0:
            continue
        if inverse:
            if head[1] > min(first[1], third[1]) - 0.5 * local_atr:
                continue
            if abs(first[1] - third[1]) > local_atr:
                continue
            neckline = (neck1[1] + neck2[1]) / 2.0
            ready = max(first[2], head[2], third[2], neck1[2], neck2[2]) + 1
            for i in range(ready, len(frame)):
                buffer = 0.1 * float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
                if float(frame["close"].iloc[i]) > neckline + buffer:
                    result.iloc[i] = 1
                    break
        else:
            if head[1] < max(first[1], third[1]) + 0.5 * local_atr:
                continue
            if abs(first[1] - third[1]) > local_atr:
                continue
            neckline = (neck1[1] + neck2[1]) / 2.0
            ready = max(first[2], head[2], third[2], neck1[2], neck2[2]) + 1
            for i in range(ready, len(frame)):
                buffer = 0.1 * float(atr.iloc[i]) if pd.notna(atr.iloc[i]) else 0.0
                if float(frame["close"].iloc[i]) < neckline - buffer:
                    result.iloc[i] = -1
                    break
    return result


def head_shoulders(frame: pd.DataFrame, inverse: bool = False) -> pd.Series:
    """Return top or inverse head-and-shoulders breakout."""
    return _head_shoulders(frame, inverse)


def detect_all(frame: pd.DataFrame) -> pd.DataFrame:
    """Return all objective pattern signals in one frame."""
    return pd.DataFrame({
        "double_bottom": double_bottom(frame),
        "double_top": double_top(frame),
        "triangle": triangle_breakout(frame),
        "flag": flag_breakout(frame),
        "head_shoulders": head_shoulders(frame),
        "inverse_head_shoulders": head_shoulders(frame, inverse=True),
    }, index=frame.index)
