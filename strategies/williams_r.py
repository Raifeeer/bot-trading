"""Indicadores Williams %R y RSI para investigación, sin ejecución."""
from __future__ import annotations

import pandas as pd


def williams_r(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return Williams %R on closed OHLC bars; zero range becomes NaN."""
    highest = frame["high"].rolling(period, min_periods=period).max()
    lowest = frame["low"].rolling(period, min_periods=period).min()
    denominator = highest - lowest
    result = -100.0 * (highest - frame["close"]) / denominator
    return result.where(denominator > 0)


def rsi(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    """Return Wilder-style RSI using rolling average gains/losses."""
    delta = frame["close"].diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0.0, pd.NA)
    result = 100.0 - (100.0 / (1.0 + rs))
    return result.where(avg_loss.notna())


def crosses_above(series: pd.Series, level: float) -> pd.Series:
    """True only on a closed-bar crossing from below/equal to above."""
    return (series > level) & (series.shift(1) <= level)


def crosses_below(series: pd.Series, level: float) -> pd.Series:
    """True only on a closed-bar crossing from above/equal to below."""
    return (series < level) & (series.shift(1) >= level)
