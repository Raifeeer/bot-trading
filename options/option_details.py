"""option_details.py

Enriquece piernas crudas de Alpaca (símbolos OCC tipo TQQQ260918C00085000)
con datos legibles por el dashboard: subyacente, tipo (C/P), strike, fecha de
vencimiento, días al vencimiento (DTE), y greeks estimados con Black-Scholes
usando la volatilidad histórica reciente del subyacente y el tipo libre de
riesgo configurado.

Usa el feed del bot (data/feed.py, con timeouts y fallback a yfinance), por lo
que un fallo aquí nunca bloquea el tick: las piernas quedan con los datos
básicos (strike/tipo/vencimiento/DTE) sin greeks.
"""
import logging
import re
from datetime import datetime, date
from math import log, sqrt, exp

import pandas as pd

logger = logging.getLogger("option_details")

_TFR = 0.045  # tipo libre de riesgo aproximado anual (configurable vía cfg)


def parse_occ(symbol: str) -> dict | None:
    """Parsea un símbolo OCC en minúsculas o mayúsculas.

    Formato OCC: <UNDERLYEND 6chars><YYMMDD><C|P><STRIKE 8digits>
    Los 3 últimos dígitos del strike son fracción cuando el strike < 1000.
    Ej: TQQQ260918C00085000 -> strike 85.000; SPY251219C00600000 -> 600.000
    """
    m = re.match(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$", symbol.upper())
    if m is None:
        return None
    underlying, exp_str, opt_char, strike_str = m.groups()
    try:
        exp_date = datetime.strptime(exp_str, "%y%m%d").date()
    except ValueError:
        return None
    strike = float(strike_str[:5] + "." + strike_str[5:])
    return {"underlying": underlying, "option_type": "CALL" if opt_char == "C" else "PUT",
            "strike": strike, "expiration_date": exp_date.isoformat()}


def _ncdf(x: float) -> float:
    """CDF de la normal estándar (aproximación de Abramowitz & Stegun 7.1.26)."""
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    poly = ((((1.330274429 * t - 1.821255978) * t + 1.781477937) * t
             - 0.356563782) * t + 0.319381530) * t
    c = 0.3989422804014327 * exp(-0.5 * x * x)
    v = 1.0 - c * poly
    return v if x >= 0 else 1.0 - v


def bs_price(spot: float, strike: float, t: float, iv: float,
             r: float, is_call: bool) -> float:
    if t <= 0.0 or iv <= 0.0 or spot <= 0.0:
        return 0.0
    d1 = (log(spot / strike) + (r + 0.5 * iv * iv) * t) / (iv * sqrt(t))
    d2 = d1 - iv * sqrt(t)
    n1 = _ncdf(d1)
    n2 = _ncdf(d2)
    if is_call:
        return spot * n1 - strike * exp(-r * t) * n2
    return strike * exp(-r * t) * (1 - n2) - spot * (1 - n1)


def bs_greeks(spot: float, strike: float, t: float, iv: float, r: float,
              is_call: bool) -> dict:
    """Delta, theta (por día calendario) y vega (por 1 punto de IV) en B&S."""
    if t <= 0.0 or iv <= 0.0 or spot <= 0.0:
        return {"delta": 0.0, "theta": 0.0, "vega": 0.0}
    sd = iv * sqrt(t)
    d1 = (log(spot / strike) + (r + 0.5 * iv * iv) * t) / sd
    d2 = d1 - sd
    nprime = 0.3989422804014327 * exp(-0.5 * d1 * d1)
    sign = 1.0 if is_call else -1.0
    delta = sign * _ncdf(d1) if is_call else _ncdf(d1) - 1.0
    theta = (-spot * nprime * iv / (2 * sqrt(t))
             - sign * r * strike * exp(-r * t) * _ncdf(sign * d2)) / 365.0
    vega = spot * sqrt(t) * nprime / 100.0  # por 1 punto de IV
    return {"delta": round(delta, 3), "theta": round(theta, 4),
            "vega": round(vega, 3)}


def _iv_from_series(close: pd.Series) -> float | None:
    closes = close.astype(float).dropna().tolist()
    if len(closes) < 15:
        return None
    rets = [log(closes[i] / closes[i - 1]) for i in range(1, len(closes))
            if closes[i - 1] > 0]
    if not rets:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return sqrt(var) * sqrt(252)


def spot_iv_from_feed(feed, underlying: str, days: int = 60):
    """Devuelve (spot, iv) del subyacente desde el feed del bot o (None, None)."""
    try:
        data = feed.history([underlying], "1d", days=days) or {}
        df = data.get(underlying)
        if df is None or not hasattr(df, "__len__") or len(df) < 15:
            return None, None
        spot = float(df["close"].astype(float).dropna().iloc[-1])
        iv = _iv_from_series(df["close"])
        return spot, iv
    except Exception:  # noqa: BLE001
        logger.exception("Fallo estimando spot/IV de %s", underlying)
        return None, None


def enrich_leg(leg: dict, spot_map: dict | None = None,
               iv_map: dict | None = None, tfr: float = _TFR) -> dict:
    """Añade option_details a una pierna cruda de Alpaca (in-place) y la devuelve."""
    parsed = parse_occ(leg.get("symbol", ""))
    if parsed is None:
        leg["option_details"] = None
        return leg
    today = date.today()
    exp = datetime.strptime(parsed["expiration_date"], "%Y-%m-%d").date()
    dte = max((exp - today).days, 0)
    underlying = parsed["underlying"]
    details = {
        "underlying": underlying,
        "option_type": parsed["option_type"],
        "strike": parsed["strike"],
        "expiration_date": parsed["expiration_date"],
        "dte": dte,
        "delta": 0.0, "theta": 0.0, "vega": 0.0,
        "iv_est": None, "spot": None, "bs_price": None,
    }
    spot = (spot_map or {}).get(underlying)
    iv = (iv_map or {}).get(underlying)
    if spot and iv:
        t = max(dte / 365.0, 0.001)
        is_call = parsed["option_type"] == "CALL"
        g = bs_greeks(spot, parsed["strike"], t, iv, tfr, is_call)
        price = bs_price(spot, parsed["strike"], t, iv, tfr, is_call)
        details.update(delta=g["delta"], theta=g["theta"], vega=g["vega"],
                       iv_est=round(iv, 3), spot=round(spot, 2),
                       bs_price=round(price, 2))
    leg["option_details"] = details
    return leg


def enrich_positions(legs: list, feed=None, tfr: float = _TFR) -> list:
    """Enriquece una lista de piernas crudas con option_details.

    Estima spot/IV una sola vez por subyacente (una llamada por ticker).
    Sin feed disponible o con fallo de proveedor, las piernas quedan con los
    datos básicos (strike/tipo/vencimiento/DTE) — nunca falla el tick.
    """
    if not legs:
        return legs
    spot_map, iv_map = {}, {}
    if feed is not None:
        underlyings = {}
        for leg in legs:
            p = parse_occ(leg.get("symbol", ""))
            if p is not None:
                underlyings.setdefault(p["underlying"], True)
        for u in underlyings:
            spot_map[u], iv_map[u] = spot_iv_from_feed(feed, u)
    for leg in legs:
        enrich_leg(leg, spot_map=spot_map, iv_map=iv_map, tfr=tfr)
    return legs
