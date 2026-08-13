"""Estrategia SMC (Smart Money Concepts) multi-timeframe.

Basada en el material MTF de Jorge Valet (Abacus PRO) y las clases de
Temporalidades de Jean Vizón:

  1. DIARIO   = perspectiva (tendencia, niveles criticos, etapa del grafico)
  2. 4H       = narrativa (continuacion o retroceso)
  3. M15      = sesgo inmediato (CHoCH confirma fin de continuacion /
                inicio de retroceso)
  4. M1       = temporizacion de la entrada

Reglas:
  - Una tendencia en HTF debe suceder primero en LTF (flujo fractal).
  - CHoCH: senal de cambio en la estructura interna; exige confluencia
    (sweep de liquidez + OB de S&D) y nunca opera sola.
  - Mapeo conservador: mechas para estructura, cuerpos para BOS.
  - Zona de demanda: vela base contraria al impulso alcista, desde el open
    hasta la mecha inferior. Zona de supply: espejo con mecha superior.
  - Objetivo: un alto debil / bajo debil en la direccion de la tendencia HTF.
"""
import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from strategies.base import Signal, SignalType

logger = logging.getLogger("smc")

TIMEFRAMES = ["1d", "4h", "15m", "1m"]


@dataclass
class Swing:
    """Punto swing: precio, indice, es alto (True) o bajo (False),
    fuerte/debil segun si causo un opuesto significativo."""
    price: float
    idx: int
    is_high: bool
    strong: bool = True


@dataclass
class Zone:
    """Zona de S&D (order block basico)."""
    kind: str          # "demand" o "supply"
    top: float
    bottom: float
    idx: int


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza columnas a Open/High/Low/Close/Volume independientemente
    de si vienen en mayusculas o minusculas."""
    mapping = {"open": "Open", "high": "High", "low": "Low",
               "close": "Close", "volume": "Volume"}
    rename = {c: mapping[c] for c in df.columns if c in mapping}
    return df.rename(columns=rename)


def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resamplear a una regla de pandas (1d/4h/15min/1min)."""
    rules = {"1d": "1D", "4h": "4h", "4H": "4h", "15m": "15min", "1m": "1min"}
    r = rules.get(rule, rule)
    df = _norm(df)
    return df.resample(r).agg({"Open": "first", "High": "max",
                               "Low": "min", "Close": "last",
                               "Volume": "sum"}).dropna()


def fractal_swing_points(df: pd.DataFrame, order: int = 3,
                         conservative: bool = True):
    """Detecta altos/bajos locales por ventana de fractales.

    conservative=True -> mapeo tipo 1: estructura con mechas (high/low),
    BOS con cuerpos (open/close).
    """
    swings = []
    df = _norm(df)
    # con series cortas (p. ej. daily de 2 semanas), reducir el orden del
    # fractal para que existan swings comparables (12 barras -> order 2)
    if len(df) < 2 * (2 * order + 1):
        order = max(1, min(order, (len(df) // 2 - 1) // 2))
    highs, lows = (df["High" if conservative else "Close"].to_numpy(),
                   df["Low" if conservative else "Close"].to_numpy())
    for i in range(order, len(df) - order):
        if highs[i] == max(highs[i - order:i + order + 1]):
            swings.append(Swing(highs[i], i, is_high=True, strong=True))
        elif lows[i] == min(lows[i - order:i + order + 1]):
            swings.append(Swing(lows[i], i, is_high=False, strong=True))
    return swings


def detect_choch(df: pd.DataFrame, order: int = 3) -> str:
    """CHoCH: cambio de caracter en el ultimo tramo de la serie.

    Devuelve "bull", "bear" o None.
    - CHoCH alcista: tras una serie de HH/HL bajista, el precio rompe por
      arriba el ultimo bajo estructural relevante con cierre.
    - CHoCH bajista: espejo.
    """
    if len(df) < 60:
        return None
    swings = fractal_swing_points(df, order)
    if len(swings) < 4:
        return None
    last = swings[-1]
    prev = swings[-2]
    prev2 = swings[-3]
    df = _norm(df)
    close = df.iloc[-1].Close
    if prev.is_high and not prev2.is_high and prev2.price > prev.price:
        # ultimo movimiento estructural: bajo estructural en prev.price
        if close > prev.price and (not last.is_high or last.price < close):
            return "bull"
    if not prev.is_high and prev2.is_high and prev2.price < prev.price:
        if close < prev.price and (last.is_high or last.price > close):
            return "bear"
    return None


def detect_sw_zone(df: pd.DataFrame, order: int = 2):
    """Zonas de supply/demanda por vela base contraria al impulso.

    Demanda: vela bajista seguida de impulso alcista -> zona [open, mecha inf].
    Supply: vela alcista seguida de impulso bajista -> zona [mecha sup, open].
    """
    df = _norm(df)
    zones = []
    o = df["Open"].to_numpy(); c = df["Close"].to_numpy()
    h = df["High"].to_numpy(); l = df["Low"].to_numpy()
    for i in range(1, len(df) - 1):
        if o[i] > c[i] and c[i + 1] > h[i]:     # base bajista -> demanda
            zones.append(Zone("demand", l[i], min(o[i], l[i]), i))
        elif c[i] > o[i] and c[i + 1] < l[i]:   # base alcista -> supply
            zones.append(Zone("supply", max(o[i], h[i]), h[i], i))
    return zones[-3:] if zones else zones


class SMCStrategy:
    """Detector MTF: determina el BIAS del dia y dispara entradas con CHoCH.

    Uso:
        smc = SMCStrategy()
        bias, conf = smc.analyze({"1d": df_d, "4h": df_4h,
                                  "15m": df_15, "1m": df_1m})
        sig = smc.to_signal(symbol, bias, spot)
    """

    name = "smc"

    def __init__(self, conservative: bool = True):
        self.conservative = conservative

    # --------------------------------------------------------------
    # Analicis MTF
    # --------------------------------------------------------------
    def trend_htf(self, df: pd.DataFrame) -> str:
        """Tendencia del timeframe alto: HH/HL (bull), LH/LL (bear),
        o "range"."""
        if df is None or len(df) < 15:
            return "range"
        # con series cortas, el fractal de order 3 puede no encontrar
        # swings: adaptar el orden al largo de la serie
        order = 3
        if len(df) < 2 * (2 * order + 1):
            order = max(1, min(order, (len(df) // 2 - 1) // 2))
        swings = fractal_swing_points(df, order=order)
        highs = [s.price for s in swings if s.is_high][-3:]
        lows = [s.price for s in swings if not s.is_high][-3:]
        if len(highs) >= 2 and len(lows) >= 2:
            if highs[-1] > highs[-2] and lows[-1] > lows[-2]:
                return "bull"
            if highs[-1] < highs[-2] and lows[-1] < lows[-2]:
                return "bear"
            return "range"
        # fallback de series muy cortas: primer/ultimo extremo local
        if len(swings) >= 2:
            first, last = swings[0].price, swings[-1].price
            if last > first * 1.01:
                return "bull"
            if last < first * 0.99:
                return "bear"
        return "range"

    def analyze(self, dfs: dict) -> dict:
        """Cascada MTF segun la clase de Temporalidades:
        1d+4h -> niveles/tendencia; M15 -> sesgo (CHoCH); M1 -> timing."""
        result = {
            "bias": None, "confluence": 0.0,
            "choch_15m": None, "htf_trend": None, "note": "",
        }
        df_d, df_4h, df_15, df_1m = (dfs.get(t) for t in TIMEFRAMES)

        # 1) Perspectiva: diario + 4H
        df_d, df_4h = (_norm(d) if d is not None else None
                       for d in (df_d, df_4h))
        d_trend = self.trend_htf(df_d)
        h_trend = self.trend_htf(df_4h)
        if d_trend == h_trend and d_trend != "range":
            result["htf_trend"] = d_trend
            result["confluence"] += 0.35
        elif d_trend != "range" and h_trend == "range":
            result["htf_trend"] = d_trend
            result["confluence"] += 0.2

        # 2) Sesgo inmediato: CHoCH en M15 (30 barras = ~1.5 sesiones de
        # 15 min; 60 exigia una semana entera y en papel raro se cumple)
        if df_15 is not None and len(df_15) >= 30:
            ch = detect_choch(df_15)
            result["choch_15m"] = ch
            if ch and result["htf_trend"] and ch == result["htf_trend"]:
                result["confluence"] += 0.35       # CHoCH alineado a HTF
            elif ch:
                result["confluence"] += 0.15       # CHoCH contra HTF: debil

        # 3) Zonas S&D en M15 (confluencia extra si el precio toca una zona
        # alineada con la tendencia HTF)
        zones = detect_sw_zone(df_15) if df_15 is not None else []
        if df_1m is not None and len(df_1m) and zones:
            df_1m = _norm(df_1m)
            px = df_1m.iloc[-1].Close
            for z in zones:
                if z.bottom <= px <= z.top:
                    if (z.kind == "demand" and result["htf_trend"] == "bull"
                            or z.kind == "supply" and result["htf_trend"] == "bear"):
                        result["confluence"] += 0.15
                        result["note"] += f"precio en zona {z.kind}; "

        # 4) Timing: entrada solo si confluencia >= 0.5
        if result["confluence"] >= 0.5 and result["htf_trend"]:
            result["bias"] = result["htf_trend"]
        elif result["confluence"] >= 0.35 and result["choch_15m"]:
            result["bias"] = result["choch_15m"]
        return result

    def to_signal(self, symbol: str, analysis: dict, spot: float) -> Signal:
        bias = analysis.get("bias")
        sig_type = SignalType.LONG if bias == "bull" else (
            SignalType.SHORT if bias == "bear" else SignalType.NONE)
        return Signal(
            symbol=symbol, signal_type=sig_type,
            score=analysis.get("confluence", 0.0),
            reason=(f"smc_mtf: bias={bias}, HTF={analysis.get('htf_trend')}, "
                    f"CHoCH15m={analysis.get('choch_15m')}, "
                    f"confluencia={analysis.get('confluence', 0):.2f} "
                    f"{analysis.get('note', '')}").rstrip(),
            strategy="smc")
