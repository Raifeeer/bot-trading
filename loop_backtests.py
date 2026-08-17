"""Loop de backtests del RETO $100 -> $200 (v2).

Itera escenarios sobre el universo del reto con tres motores de señal:
  - swing:        cruce SMA20/50 alcista + precio > SMA50; exit cruce bajista
                  o gestión 21DTE.
  - smc_daily:    tendencia estructural diaria (HH/HL) == "bull"; exit pasa a
                  "bear" o gestión.
  - rsi_bounce:   RSI14 < 30 + precio > SMA200 (rebote); exit RSI > 70 o
                  cruce bajista.

Gestión de opciones igual que el bot: call spread valorado con BS (realized
vol 20d + superficie simple), TP/SL sobre la prima, cierre por DTE.

Salida: /home/ubuntu/backtests/bt_resumen.csv + trades/equity por escenario.
Uso: python loop_backtests.py [--scenario X] [--all]
"""
import argparse
import os
import sys
import time
import warnings

import numpy as np
import pandas as pd
import ta
from scipy import stats

warnings.filterwarnings("ignore")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data.feed import MarketDataFeed
from options.chains import black_scholes_price, OptionType
from strategies.smc import (SMCStrategy, detect_choch,
                              fractal_swing_points)

CAPITAL_INICIAL = 100.0
N_DIAS_HIST = 300
R = 0.045
MARGIN_MULT = 1.2

UNI_RETO = ["SOFI", "PLTR", "F", "TSLA", "AMD", "NOK", "BB", "TQQQ"]
UNI_TECH = ["NVDA", "TSLA", "AMD", "PLTR", "AAPL", "AMZN", "META", "MSFT", "GOOGL"]
UNI_ETF = ["SPY", "QQQ", "IWM", "TQQQ", "SQQQ"]
UNI_AMPLIO = UNI_ETF + UNI_TECH[:5]
EARNINGS_WINDOW_DAYS = 8

# --------------------------------------------------------------- indicadores
def sma(series, n):
    return series.rolling(n).mean()


def rsi(series, n=14):
    return ta.momentum.RSIIndicator(series, n).rsi()


def realized_vol(df, window=20):
    ret = np.log(df["close"] / df["close"].shift(1)).dropna()
    return float(ret.rolling(window).std().iloc[-1] * np.sqrt(252)) if len(ret) >= window else 0.3


def earn_dates_for(sym, df):
    """Un reporte por trimestre: día de mayor |log-return| del trimestre."""
    try:
        ret = np.log(df["close"] / df["close"].shift(1)).abs().reindex(df.index)
        out = []
        for _qname, grp in df.groupby(df.index.to_period("Q")):
            if len(grp) < 20:
                continue
            sub = ret.loc[grp.index].dropna()
            if len(sub):
                out.append(sub.idxmax().normalize())
        return out
    except Exception:
        return []


# --------------------------------------------------------------- señales
def swing_entry(hist, d):
    """Cruce SMA20/50 alcista con precio sobre SMA50. Devuelve dict o None."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 55:
        return None
    s20, s50 = sma(sub["close"], 20), sma(sub["close"], 50)
    prev_c = s20.iloc[-2] <= s50.iloc[-2] and s20.iloc[-1] > s50.iloc[-1]
    if not prev_c:
        return None
    if sub["close"].iloc[-1] <= s50.iloc[-1]:
        return None
    return dict(type="swing")


def swing_exit(hist, d):
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 55:
        return False
    s20, s50 = sma(sub["close"], 20), sma(sub["close"], 50)
    return bool(s20.iloc[-2] >= s50.iloc[-2] and s20.iloc[-1] < s50.iloc[-1])


def smc_entry(hist, d):
    """Tendencia estructural diaria bull (HH/HL), con CHoCH alcista reciente."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 60:
        return None
    smc = SMCStrategy()
    t = smc.trend_htf(sub)
    ch = detect_choch(sub)
    if t == "bull" and (ch == "bull" or ch is None):
        return dict(type="smc_daily")
    return None


def smc_exit(hist, d):
    """Sale solo si la tendencia estructural diaria pasa a bear."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 60:
        return False
    smc = SMCStrategy()
    return smc.trend_htf(sub) == "bear"


def mr_entry(hist, d):
    """Mean reversion profundo: precio > SMA100 pero RSI14 < 25 (dip fuerte
    en tendencia media)."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 110:
        return None
    r = rsi(sub["close"])
    s100 = sma(sub["close"], 100)
    last = sub.iloc[-1]
    if pd.notna(r.iloc[-1]) and r.iloc[-1] < 25 and pd.notna(s100.iloc[-1]) \
            and last["close"] > s100.iloc[-1]:
        return dict(type="mean_rev")
    return None


def put_entry(hist, d):
    """Put spread: tendencia estructural diaria bear."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 60:
        return None
    smc = SMCStrategy()
    t = smc.trend_htf(sub)
    if t == "bear":
        return dict(type="put_smc")
    return None


def put_exit(hist, d):
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 60:
        return False
    smc = SMCStrategy()
    return smc.trend_htf(sub) == "bull"


def mr_exit(hist, d):
    """Exit por recuperación (RSI>55) o pérdida de soporte (precio < SMA100)."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 110:
        return False
    r = rsi(sub["close"])
    s100 = sma(sub["close"], 100)
    if pd.isna(r.iloc[-1]):
        return False
    if r.iloc[-1] > 55:
        return True
    if pd.notna(s100.iloc[-1]) and sub["close"].iloc[-1] < s100.iloc[-1]:
        return True
    return False


def rsi_entry(hist, d, floor=200):
    """Rebote: RSI14 < 30 y precio sobre SMA(filtro)."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < max(floor, 60) + 5:
        return None
    r = rsi(sub["close"])
    sf = sma(sub["close"], floor)
    last = sub.iloc[-1]
    if pd.notna(sf.iloc[-1]) and last["close"] > sf.iloc[-1] and pd.notna(r.iloc[-1]) and r.iloc[-1] < 30:
        return dict(type="rsi_bounce")
    return None


def rsi_exit(hist, d, floor=200):
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < max(floor, 60) + 5:
        return False
    r = rsi(sub["close"])
    sf = sma(sub["close"], floor)
    if pd.isna(r.iloc[-1]):
        return False
    if r.iloc[-1] > 70:
        return True
    if pd.notna(sf.iloc[-1]) and sub["close"].iloc[-1] < sf.iloc[-1]:
        return True
    s20, s50 = sma(sub["close"], 20), sma(sub["close"], 50)
    if len(sub) >= 55 and s20.iloc[-2] >= s50.iloc[-2] and s20.iloc[-1] < s50.iloc[-1]:
        return True
    return False



# regime_hold_cash: bull => hold semanal, bear => cash (no puts caras,
# hipótesis de la ronda 9: puts con comisiones dejan ~break-even)

MOTORES = {"swing": (swing_entry, swing_exit),
           "smc_daily": (smc_entry, smc_exit),
           "rsi_bounce": (rsi_entry, rsi_exit),
           "mean_rev": (mr_entry, mr_exit),
           "put_smc": (put_entry, put_exit),
           "both": (smc_entry, None),  # both usa lógica especial abajo
           "hold": (None, None)}

# --------------------------------------------------------------- opciones
def delta_call(spot, k, T, r, sigma):
    d1 = (np.log(spot / k) + (r + sigma ** 2 / 2) * T) / (sigma * np.sqrt(T))
    return float(stats.norm.cdf(d1))


def strike_for_delta(spot, target_delta, T, r, sigma, lo=None, hi=None):
    lo, hi = lo or spot * 0.8, hi or spot * 1.3
    for _ in range(60):
        mid = (lo + hi) / 2
        if delta_call(spot, mid, T, r, sigma) > target_delta:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def build_spread(spot, sigma_atm, entry_date, sc, side="call"):
    """Construye spread debit vertical. side: call (alcista) o put (bajista)."""
    T = sc["dte"] / 365.0
    otype = OptionType.CALL if side == "call" else OptionType.PUT
    if side == "call":
        k_long = strike_for_delta(spot, sc["delta_l"], T, R, sigma_atm)
        k_short = strike_for_delta(spot, sc["delta_s"], T, R, sigma_atm)
    else:  # puts: pata long = strike MAYOR (más ATM, delta mayor, más cara);
        # pata short = strike MENOR (más OTM). Débito = px_long - px_short > 0
        k_long = strike_for_delta(spot, 1 - sc["delta_l"], T, R, sigma_atm)
        k_short = strike_for_delta(spot, 1 - sc["delta_s"], T, R, sigma_atm)
    px_l = black_scholes_price(spot, k_long, T, R, sigma_atm, otype)
    px_s = black_scholes_price(spot, k_short, T, R, sigma_atm, otype)
    net = (px_l - px_s) * 100 * MARGIN_MULT
    if net <= 0:
        return None
    return dict(k_long=k_long, k_short=k_short, px_l=px_l, px_s=px_s,
                net=net, t=T, entry_date=entry_date, sigma=sigma_atm,
                side=side)


def value_spread(spread, spot, days_later, sc, exit_spot=None):
    """exit_spot: si se pasa, usarlo como spot final (evolución real del día)."""
    T = max((spread["t"] * 365.0 - days_later), 0) / 365.0
    sig = spread["sigma"]
    s_final = exit_spot if exit_spot is not None else spot
    side = spread.get("side", "call")
    otype = OptionType.CALL if side == "call" else OptionType.PUT
    if T <= 0:
        if side == "call":
            v = (max(s_final - spread["k_long"], 0) - max(s_final - spread["k_short"], 0)) * 100
        else:
            v = (max(spread["k_short"] - s_final, 0) - max(spread["k_long"] - s_final, 0)) * 100
        return v * MARGIN_MULT
    px_l = black_scholes_price(s_final, spread["k_long"], T, R, sig, otype)
    px_s = black_scholes_price(s_final, spread["k_short"], T, R, sig, otype)
    return (px_l - px_s) * 100 * MARGIN_MULT


# Asignacion minima por pata: por debajo de esto la cuenta esta agotada y no
# se abre nada (una pata de $0 rompia pnl_pct = pnl / entry_net).
_MIN_PER = 0.01


def _safe_per_symbol(equity: float, n_syms: int, sc: dict,
                     committed: float = 0.0) -> float:
    """Reparto por símbolo para las rutas de 'hold' equally weighted.

    El motor tiene cuatro contabilidades de equity duplicadas (`equity`,
    `equity2`, `equity3`, `equity3b`) y las tres de reparto repartían el
    equity ENTERO entre los símbolos, sin descontar lo ya comprometido ni
    reservar la comisión que se cobra al cerrar cada pata. Con la cuenta casi
    vacía, esa comisión la empujaba a negativo (-102% / equity -1.95
    observado el 17 ago 2026). Este helper centraliza la aritmética segura:
    nunca compromete más que el capital libre menos la comisión de salida.
    """
    n = max(int(n_syms), 1)
    libre = max(0.0, float(equity) - float(committed))
    reserva = n * float(sc.get("comision") or 0.0)
    return max(0.0, libre - reserva) / n


def _roundtrip_commission(sc: dict) -> float:
    """Comisión total de una operación completa de spread: 2 patas x
    (entrada + salida). Se cobra al cerrar, pero debe reservarse al entrar."""
    return 4.0 * float(sc.get("comision") or 0.0)


def option_entry_cost(spread: dict, sc: dict) -> float:
    """Costo de entrada con slippage por contrato; 0 por defecto para legacy."""
    slip = max(0.0, float(sc.get("slippage_pct", 0.0)))
    return float(spread["net"]) * (1.0 + slip)


def option_exit_value(spread: dict, spot: float, days_later: int,
                      sc: dict, exit_spot: float | None = None) -> float:
    """Valor de salida neto después de slippage; modelado, no fill real."""
    slip = max(0.0, float(sc.get("slippage_pct", 0.0)))
    gross = value_spread(spread, spot, days_later, sc, exit_spot=exit_spot)
    return max(0.0, gross * (1.0 - slip))


def equity_entry_cost(amount: float, sc: dict) -> float:
    """Costo equity de entrada; `equity_cost_pct` representa ida y vuelta."""
    cost = max(0.0, float(sc.get("equity_cost_pct", 0.0)))
    return float(amount) * (1.0 + cost / 2.0)


def _ref_spot(pos: dict) -> float:
    """Precio de referencia para valorar una pata de acciones: el de ENTRADA.

    Bug encontrado el 17 ago 2026: el bucle diario refrescaba
    `pos["last_spot"]` con el cierre de cada dia, y los cierres valoraban
    contra ese mismo campo. El cociente salia siempre 1 y el pnl exactamente
    0.0: las patas de acciones del motor `regime_aware` no podian registrar
    ganancia ni perdida (72 de 74 trades con pnl 0 y pnl maximo +0.0000).
    `entry_spot` es inmutable; `last_spot` se mantiene solo como ultimo precio
    conocido para cuando falta la barra del dia de salida.
    """
    return float(pos.get("entry_spot") or pos["last_spot"])


def equity_exit_value(entry_net: float, exit_spot: float,
                      last_spot: float, sc: dict) -> float:
    """Valor equity de salida después de la mitad del coste round-trip."""
    cost = max(0.0, float(sc.get("equity_cost_pct", 0.0)))
    return max(0.0, float(entry_net) * (exit_spot / last_spot) * (1.0 - cost / 2.0))


# --------------------------------------------------------------- escenarios
SCENARIOS = {
    # --- Motores puros, universo reto ---
    "S1": dict(name="Swing en universo reto", motor="swing", window_days=90,
               tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
               delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
               max_rv=None, anti_earnings=False),
    "S2": dict(name="SMC diario en universo reto", motor="smc_daily", window_days=90,
               tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
               delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
               max_rv=None, anti_earnings=False),
    "S3": dict(name="RSI bounce en universo reto", motor="rsi_bounce", window_days=90,
               tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
               delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
               max_rv=None, anti_earnings=False),
    # --- Variaciones de riesgo/gestión sobre el mejor motor (se define tras ronda 1) ---
    "S4": dict(name="Swing riesgo 30%", motor="swing", window_days=90,
               tickers=UNI_RETO, risk_pct=0.30, max_pos=2, dte=21,
               delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
               max_rv=None, anti_earnings=False),
    "S5": dict(name="Swing gestión apretada", motor="swing", window_days=90,
               tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=14,
               delta_l=0.30, delta_s=0.15, tp=1.3, sl=0.4,
               max_rv=None, anti_earnings=False),
    "S6": dict(name="Swing spread OTM 0.25/0.10", motor="swing", window_days=90,
               tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
               delta_l=0.25, delta_s=0.10, tp=1.5, sl=0.15,
               max_rv=None, anti_earnings=False),
    # --- Filtros de calidad ---
    "S7": dict(name="Swing + RV<60%", motor="swing", window_days=90,
               tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
               delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
               max_rv=0.60, anti_earnings=False),
    "S8": dict(name="Swing anti-earnings", motor="swing", window_days=90,
               tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
               delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
               max_rv=None, anti_earnings=True),
    # --- Universos ---
    "S9": dict(name="Swing en ETFs", motor="swing", window_days=90,
               tickers=UNI_ETF, risk_pct=0.20, max_pos=2, dte=21,
               delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
               max_rv=None, anti_earnings=False),
    "S10": dict(name="Swing en tech amplio", motor="swing", window_days=90,
                tickers=UNI_TECH, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
                max_rv=None, anti_earnings=False),
    "S11": dict(name="Swing universo amplio", motor="swing", window_days=90,
                tickers=UNI_AMPLIO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.15,
                max_rv=None, anti_earnings=False),
    # --- Combinación ganadora (hipótesis: rebote + filtros) ---
    "S12": dict(name="Swing RV<60% + anti-earnings + TP1.4", motor="swing", window_days=90,
                tickers=UNI_RETO, risk_pct=0.25, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.4, sl=0.4,
                max_rv=0.60, anti_earnings=True),
    "S13": dict(name="RSI bounce anti-earnings + RV<60%", motor="rsi_bounce", window_days=90,
                tickers=UNI_RETO, risk_pct=0.25, max_pos=2, dte=14,
                delta_l=0.30, delta_s=0.15, tp=1.3, sl=0.4,
                max_rv=0.60, anti_earnings=True),
    # --- Ronda 2: universos baratos y estructuras low-cost ---
    "S14": dict(name="Swing tickers baratos F/BB/NOK", motor="swing", window_days=90,
                tickers=["F", "BB", "NOK"], risk_pct=0.40, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.4, sl=0.4,
                max_rv=None, anti_earnings=False),
    "S15": dict(name="Swing tickers baratos SOFI+", motor="swing", window_days=90,
                tickers=["F", "BB", "NOK", "SOFI"], risk_pct=0.40, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.4, sl=0.4,
                max_rv=None, anti_earnings=False),
    "S16": dict(name="Swing OTM 0.20/0.10 riesgo 50%", motor="swing", window_days=90,
                tickers=UNI_RETO, risk_pct=0.50, max_pos=1, dte=21,
                delta_l=0.20, delta_s=0.10, tp=1.4, sl=0.4,
                max_rv=None, anti_earnings=False),
    "S17": dict(name="Swing DTE corto 10d", motor="swing", window_days=90,
                tickers=["F", "BB", "NOK", "SOFI"], risk_pct=0.40, max_pos=2, dte=10,
                delta_l=0.30, delta_s=0.15, tp=1.3, sl=0.4,
                max_rv=None, anti_earnings=False),
    "S18": dict(name="SMC tickers baratos", motor="smc_daily", window_days=90,
                tickers=["F", "BB", "NOK", "SOFI"], risk_pct=0.40, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.4, sl=0.4,
                max_rv=None, anti_earnings=False),
    "S19": dict(name="RSI bounce tickers baratos", motor="rsi_bounce", window_days=90,
                tickers=["F", "BB", "NOK", "SOFI"], risk_pct=0.40, max_pos=2, dte=14,
                delta_l=0.30, delta_s=0.15, tp=1.3, sl=0.4,
                max_rv=0.60, anti_earnings=False),
    "S20": dict(name="Swing tickers baratos anti-earnings", motor="swing", window_days=90,
                tickers=["F", "BB", "NOK", "SOFI"], risk_pct=0.40, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.4, sl=0.4,
                max_rv=None, anti_earnings=True),
    # --- Ronda 3: calibración sobre S2 ganador ---
    "S21": dict(name="SMC UNI_RETO trailing TP1.6", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.6, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S22": dict(name="SMC UNI_RETO riesgo 15%", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S23": dict(name="SMC UNI_RETO DTE 30", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=30,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S24": dict(name="SMC + RV<65%", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=0.65, anti_earnings=False),
    "S25": dict(name="SMC + anti-earnings", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S26": dict(name="Mean reversion UNI_RETO", motor="mean_rev", window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=14,
                delta_l=0.30, delta_s=0.15, tp=1.3, sl=0.4,
                max_rv=None, anti_earnings=False),
    "S27": dict(name="Mean reversion tickers baratos", motor="mean_rev", window_days=90,
                tickers=["F", "BB", "NOK", "SOFI"], risk_pct=0.30, max_pos=2, dte=14,
                delta_l=0.30, delta_s=0.15, tp=1.3, sl=0.4,
                max_rv=None, anti_earnings=False),
    "S28": dict(name="Swing señal relajada", motor="swing", window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S29": dict(name="SMC ventana 180d", motor="smc_daily", window_days=180,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S30": dict(name="SMC ventana 300d", motor="smc_daily", window_days=280,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    # --- Ronda 4: refinamiento de S22/S25 ---
    "S31": dict(name="SMC rv<70 + anti-earn risk15", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=0.70, anti_earnings=True),
    "S32": dict(name="SMC anti-earn TP2.0", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.15, tp=2.0, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S33": dict(name="SMC anti-earn risk10", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.10, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S34": dict(name="SMC DTE30 + anti-earn", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=30,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S35": dict(name="SMC delta 0.25/0.12", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.25, delta_s=0.12, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S36": dict(name="SMC spread 0.30/0.10", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S37": dict(name="SMC DTE 14 + anti-earn", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=14,
                delta_l=0.30, delta_s=0.15, tp=1.3, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S38": dict(name="SMC rv<55 + anti-earn", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.15, tp=1.5, sl=0.5,
                max_rv=0.55, anti_earnings=True),
    # --- Ronda 5: refinamiento del líder S36 + put spreads + walk-forward ---
    "S39": dict(name="S36 + TP 1.8", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.8, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S40": dict(name="S36 + rv<70", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=0.70, anti_earnings=True),
    "S41": dict(name="S36 + DTE 25", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=25,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S42": dict(name="S36 exposición 2x20%", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S43": dict(name="Put spread bearish", motor="put_smc", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S44": dict(name="Doble lado call+put", motor="both", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S45": dict(name="S36 TP 1.5 SL 0.35", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.35,
                max_rv=None, anti_earnings=True),
    "S46": dict(name="S36 TP 1.3 SL 0.5", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.3, sl=0.5,
                max_rv=None, anti_earnings=True),
    # --- Ronda 6: confirmación HTF, walk-forward, comisiones, benchmark ---
    "S47": dict(name="SMC + precio>SMA200", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, above_sma200=True),
    "S48": dict(name="SMC + volumen spark", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, volume_spark=True),
    "S49": dict(name="SMC+SMA200+vol", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True,
                above_sma200=True, volume_spark=True),
    "S50": dict(name="S36 con comisiones", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65),
    "S51": dict(name="Benchmark hold tickers semanal", motor="hold_weekly", window_days=90,
                tickers=UNI_RETO, risk_pct=0.25, max_pos=8, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S52": dict(name="S36 risk 12%", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.12, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S53": dict(name="S36 max_pos 4 risk 15%", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=4, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    # --- Ronda 7: windows bajistas/laterales + sizing mínimo + hold alternante ---
    "S54": dict(name="S36 selloff invierno (enero)", motor="smc_daily",
                window_dates=("2026-01-01", "2026-04-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S55": dict(name="S36 ventana lateral (sep-dic 25)", motor="smc_daily",
                window_dates=("2025-09-01", "2025-12-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S56": dict(name="S36 selloff + comisiones", motor="smc_daily",
                window_dates=("2026-01-01", "2026-04-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65),
    "S57": dict(name="Benchmark hold semanal selloff", motor="hold_weekly",
                window_dates=("2026-01-01", "2026-04-01"),
                tickers=UNI_RETO, risk_pct=0.25, max_pos=8, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S58": dict(name="Benchmark hold semanal lateral", motor="hold_weekly",
                window_dates=("2025-09-01", "2025-12-01"),
                tickers=UNI_RETO, risk_pct=0.25, max_pos=8, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S59": dict(name="S36 sizing min $12", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, min_net=12.0),
    "S60": dict(name="S36 sizing min $8 + comisiones", motor="smc_daily", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, min_net=8.0, comision=0.65),
    "S61": dict(name="Puts selloff enero", motor="put_smc",
                window_dates=("2026-01-01", "2026-04-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S62": dict(name="Doble lado + hold fallback", motor="both", window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, hold_idle_days=10),
    # --- Ronda 8: regime-aware + puts CHoCH + hold con comisiones ---
    "S63": dict(name="Puts CHoCH selloff", motor="put_choch",
                window_dates=("2026-01-01", "2026-04-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S64": dict(name="Regime-aware completo", motor="regime_aware",
                window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S65": dict(name="Hold semanal benchmark", motor="hold_weekly",
                window_days=90,
                tickers=UNI_RETO, risk_pct=0.25, max_pos=8, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S66": dict(name="Puts CHoCH ventana reciente", motor="put_choch",
                window_days=90,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    # --- Ronda 9: puts low-cost y regime completo ---
    "S67": dict(name="Puts CHoCH DTE 10 delta 0.25/0.08", motor="put_choch",
                window_days=90,
                tickers=UNI_RETO, risk_pct=0.20, max_pos=2, dte=10,
                delta_l=0.25, delta_s=0.08, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S68": dict(name="Puts CHoCH risk 30% (agresivo)", motor="put_choch",
                window_days=90,
                tickers=UNI_RETO, risk_pct=0.30, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S69": dict(name="Puts CHoCH + comisiones", motor="put_choch",
                window_dates=("2026-01-01", "2026-04-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65),
    "S70": dict(name="Regime agresivo risk 30%", motor="regime_aware",
                window_days=90,
                tickers=UNI_RETO, risk_pct=0.30, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
    "S71": dict(name="Regime selloff ene-abr", motor="regime_aware",
                window_dates=("2026-01-01", "2026-04-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True),
}


def put_choch_entry(hist, d):
    """Put spread: CHoCH bajista pragmático.
    Estructura: tras un rango con HI dominante, el cierre rompe por DEBAJO
    del último swing LOW relevante (cambio de carácter bearish)."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 60:
        return None
    sw = fractal_swing_points(sub, 3)
    if len(sw) < 4:
        return None
    # buscar la secuencia HI dominante reciente: últimos 4 swings
    last4 = sw[-4:]
    his = [s.price for s in last4 if s.is_high]
    los = [s.price for s in last4 if not s.is_high]
    if not his or not los:
        return None
    last_hi = max(his)
    # último LO dominante (el más reciente)
    last_lo_swing = los[-1]
    close = sub["close"].iloc[-1]
    # el precio cerró por debajo del LO estructural y el HI dominante
    # fue reciente (<60 días): CHoCH bear
    hi_idx = None
    for s in last4:
        if s.is_high and s.price == last_hi:
            hi_idx = s.idx
            break
    n_days_since_hi = (d - sub.index[hi_idx]).days if hi_idx is not None else 999
    if close < last_lo_swing and n_days_since_hi < 60:
        return dict(type="put_choch")
    return None


MOTORES["put_choch"] = (put_choch_entry, put_exit)
MOTORES["regime_hold_cash"] = (None, None)  # lógica propia en run_scenario
MOTORES["regime_aware"] = (None, None)  # lógica propia abajo

# --- Ronda 10: motores nuevos (definiciones ANTES de MOTORES para orden de lectura)
def rebote_rsi_entry(hist, d):
    """Cruce tras dip profundo: precio cae -15% del máximo 60d y RSI14<30,
    luego RSI cruza de vuelta por encima de 25. Típico del rebote de jul-2026."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 80:
        return None
    win60 = sub["close"].iloc[-60:]
    hi = win60.max()
    r = rsi(sub["close"])
    close_now = sub["close"].iloc[-1]
    dip_ok = close_now <= hi * 0.85
    rsi_now = r.iloc[-1]
    if pd.isna(rsi_now) or not dip_ok:
        return None
    if rsi_now >= 25 and r.iloc[-2] < 25:  # cruce alcista desde oversold
        return dict(type="rebote_rsi")
    return None


def rebote_rsi_exit(hist, d):
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 60:
        return False
    r = rsi(sub["close"])
    return bool(pd.notna(r.iloc[-1]) and r.iloc[-1] > 70)
MOTORES["rebote_rsi"] = (rebote_rsi_entry, rebote_rsi_exit)


def breakout_entry(hist, d, lookback=20, volume_mult=1.2):
    """Ruptura de máximos previos con confirmación de volumen.

    El día de decisión solo puede usar el cierre y volumen de `d` y las
    barras anteriores. No se usa ninguna fila posterior al corte.
    """
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < max(lookback + 1, 40):
        return None
    prior = sub.iloc[-lookback-1:-1]
    last = sub.iloc[-1]
    vol_ref = sub["volume"].iloc[-min(len(sub), lookback + 20):-1].mean()
    if (pd.notna(last["close"]) and last["close"] > prior["high"].max()
            and pd.notna(vol_ref) and last["volume"] >= vol_ref * volume_mult):
        return dict(type=f"breakout_{lookback}")
    return None


def breakout_exit(hist, d):
    """Salir si el cierre pierde la SMA20, evitando perseguir rupturas fallidas."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 25:
        return False
    s20 = sma(sub["close"], 20)
    return bool(pd.notna(s20.iloc[-1]) and sub["close"].iloc[-1] < s20.iloc[-1])


MOTORES["breakout20"] = (
    lambda hist, d: breakout_entry(hist, d, lookback=20, volume_mult=1.2),
    breakout_exit,
)
MOTORES["breakout55"] = (
    lambda hist, d: breakout_entry(hist, d, lookback=55, volume_mult=1.2),
    breakout_exit,
)

def run_scenario(key: str, sc: dict, data: dict):
    # El universo del escenario DEBE aplicarse aquí: los bucles de entrada de
    # las rutas no-regime iteran `sorted(data.items())`, así que sin filtrar
    # operaban sobre todos los tickers descargados e ignoraban por completo
    # `sc["tickers"]` — dos escenarios con universos distintos devolvían
    # resultados idénticos byte a byte (detectado el 17 ago 2026, invalida las
    # conclusiones por universo del corpus histórico S1-S89).
    universo = set(sc.get("tickers") or data.keys())
    data = {s: df for s, df in data.items() if s in universo}
    if not data:
        raise ValueError(f"{key}: ningún ticker del universo {sorted(universo)} "
                         f"está en los datos")

    today = pd.Timestamp.now(tz="UTC").normalize()
    if sc.get("window_dates"):
        start = pd.Timestamp(sc["window_dates"][0], tz="UTC").normalize()
        end = pd.Timestamp(sc["window_dates"][1], tz="UTC").normalize()
    else:
        end = today
        start = today - pd.Timedelta(days=sc["window_days"])

    is_regime = sc["motor"] in ("regime_aware", "regime_hold_cash")
    is_hold = sc["motor"] in ("hold", "hold_weekly")
    entry_fn, exit_fn = (None, None) if is_hold else MOTORES[sc["motor"]]
    if not is_hold and exit_fn is None:  # motor "both": salida por señal contraria
        def exit_fn(hist, d):  # noqa: E303
            sub = hist[hist.index.normalize() <= d]
            if len(sub) < 60:
                return False
            smc = SMCStrategy()
            t = smc.trend_htf(sub)
            return t == "bear"  # call spread exit si el trend se revierte
    earn_dates = {sym: earn_dates_for(sym, df) for sym, df in data.items()} \
        if sc.get("anti_earnings") else {}

    equity = CAPITAL_INICIAL
    open_pos, trades, equity_curve = [], [], []

    dates = sorted({ts.normalize() for df in data.values() for ts in df.index})
    dates = [d for d in dates if start <= d <= end]

    for d in dates:
        # cerrar posiciones vencidas por señal de salida o gestión
        still_open = []
        for pos in open_pos:
            days_held = (d - pos["entry_date"]).days
            exit_df = data[pos["symbol"]]
            exit_spot = pos["last_spot"]
            exit_rows = exit_df[exit_df.index.normalize() == d]
            if len(exit_rows):
                exit_spot = float(exit_rows["close"].iloc[-1])
            if pos.get("side") == "equity":  # motor hold: valor por cambio spot
                val = equity_exit_value(pos["entry_net"], exit_spot, _ref_spot(pos), sc)
            else:
                val = option_exit_value(pos["spread"], pos["last_spot"],
                                        days_held, sc, exit_spot=exit_spot)
            entry_net = pos["entry_net"]
            cur = val / entry_net if entry_net > 0 else 0
            reason = ""
            if is_hold:
                if days_held >= 1:
                    reason = "hold_window"
            elif days_held >= 1 and cur >= sc["tp"]:
                reason = f"tp_{sc['tp']:.1f}"
            elif days_held >= 1 and cur <= sc["sl"]:
                reason = f"sl_{sc['sl']:.1f}"
            if not reason and days_held >= 3 and exit_fn(data[pos["symbol"]], d):
                reason = "senal_exit"
            if not reason and sc.get("anti_earnings") \
                    and any(abs((d - e).days) <= EARNINGS_WINDOW_DAYS
                            for e in earn_dates.get(pos["symbol"], [])):
                reason = "anti_earnings"
            if reason:
                pnl = val - entry_net
                if pos.get("side") != "equity" and sc.get("comision"):
                    pnl -= 2.0 * sc["comision"] * 2  # 2 patas × $0.65, entr+sal
                equity += pnl
                trades.append(dict(symbol=pos["symbol"], entry_date=pos["entry_date"],
                                   exit_date=d, entry_premium=entry_net,
                                   exit_value=val, pnl=pnl,
                                   pnl_pct=pnl / entry_net, reason=reason,
                                   days_held=days_held, motor=pos["motor"]))
                continue
            still_open.append(pos)
        open_pos = still_open

        # entradas
        if len(open_pos) < sc["max_pos"] and not is_regime:
            smc_helper = SMCStrategy()
            for sym, df in sorted(data.items()):
                if any(p["symbol"] == sym for p in open_pos):
                    continue
                if is_hold:
                    entry = dict(type="hold")
                else:
                    entry = entry_fn(df, d)
                if not entry:
                    continue
                hist = df[df.index.normalize() <= d]
                if sc.get("above_sma200"):
                    s200 = sma(hist["close"], 200)
                    if pd.isna(s200.iloc[-1]) or hist["close"].iloc[-1] < s200.iloc[-1]:
                        continue
                if sc.get("volume_spark"):
                    v20 = hist["volume"].rolling(20).mean()
                    if len(hist) >= 20 and hist["volume"].iloc[-1] < v20.iloc[-1]:
                        continue
                rv = realized_vol(df[df.index.normalize() <= d])
                if sc.get("max_rv") and rv > sc["max_rv"]:
                    continue
                if len(hist) < 60:
                    continue
                if sc.get("anti_earnings") and any(
                        abs((d - e).days) <= EARNINGS_WINDOW_DAYS
                        for e in earn_dates.get(sym, [])):
                    continue
                spot = hist["close"].iloc[-1]
                sigma = rv or 0.3
                side = "put" if (sc["motor"] == "put_smc"
                                 or (sc["motor"] == "both"
                                     and smc_helper.trend_htf(hist) == "bear")) else "call"
                spread = build_spread(spot, sigma, d, sc, side=side)
                if spread is None:
                    continue
                # `net` está en USD por contrato (incluye multiplicador y
                # margen). cheap_min_net evita spreads degenerados de prima
                # casi cero en los universos de tickers baratos.
                min_net = sc.get("min_net", sc.get("cheap_min_net"))
                if min_net is not None and spread["net"] < min_net:
                    continue
                risk_budget = equity * sc["risk_pct"]
                entry_net = option_entry_cost(spread, sc)
                # Contabilidad de caja: el equity solo se actualiza al CERRAR
                # (`equity += pnl`), así que sin descontar lo ya comprometido
                # en posiciones abiertas el motor podía comprar max_pos veces
                # el mismo % del equity total y acabar gastando más de lo que
                # tenía — con equity final negativo (-102% observado el 17 ago
                # 2026). Además, una cuenta a cero no puede seguir operando.
                committed = sum(p["entry_net"] for p in open_pos)
                available = equity - committed
                if equity <= 0 or available <= 0:
                    continue
                # La comisión se cobra al CERRAR (4 patas-lado), así que el
                # disponible tiene que cubrir también ese coste futuro: si no,
                # una entrada que gasta todo el saldo y pierde deja la cuenta
                # en negativo.
                if entry_net + _roundtrip_commission(sc) > min(risk_budget + _roundtrip_commission(sc), available):
                    continue
                open_pos.append(dict(symbol=sym, spread=spread,
                                     entry_net=entry_net,
                                     last_spot=spot, entry_date=d,
                                     motor=sc["motor"], side=side))
                break
            if is_hold and not open_pos and equity > 0:
                # idle hold: no entrar si no pasó enough days desde el inicio
                if sc.get("hold_idle_days") and (d - dates[0]).days < sc["hold_idle_days"]:
                    continue
                for sym, df in sorted(data.items()):
                    if any(p["symbol"] == sym for p in open_pos):
                        continue
                    rv = realized_vol(df[df.index.normalize() <= d])
                    spot = df["close"].iloc[-1]
                    if sc.get("max_rv") and rv and rv > sc["max_rv"]:
                        continue
                    entry_net = min(equity / (len(data) - len(open_pos)),
                                    equity * sc["risk_pct"])
                    committed_h = sum(p["entry_net"] for p in open_pos)
                    available_h = equity - committed_h
                    if equity <= 0 or available_h <= 0 or entry_net > available_h:
                        continue
                    open_pos.append(dict(symbol=sym, spread=None,
                                         entry_net=entry_net,
                                         last_spot=spot, entry_spot=spot,
                                         entry_date=d,
                                         motor="hold", side="equity"))
                    if len(open_pos) >= sc["max_pos"]:
                        break

        equity_curve.append(dict(date=d, equity=round(equity, 2),
                                 open_positions=len(open_pos)))

    smc_helper_regime = SMCStrategy() if is_regime else None
    if is_regime:
        # motor regime-aware: selección de acción según régimen HTF
        #   bull => hold semanal (equally weighted)
        #   bear (CHoCH pragmático) => put spreads
        #   lateral => cash (no hace nada)
        equity3 = CAPITAL_INICIAL
        pos3, trades3, ec3 = [], [], []
        next_rebal = dates[0]
        rebal_syms = sorted(sc["tickers"])
        for d in dates:
            # valorar posiciones abiertas de spread
            still3 = []
            for pos in pos3:
                days_held = (d - pos["entry_date"]).days
                if pos.get("side") == "equity":
                    rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == d]
                    exit_spot = float(rows["close"].iloc[-1]) if len(rows) else pos["last_spot"]
                    pos["last_spot"] = exit_spot
                else:
                    val = option_exit_value(pos["spread"], pos["last_spot"],
                                            days_held, sc)
                    entry_net = pos["entry_net"]
                    cur = val / entry_net if entry_net > 0 else 0
                    reason = ""
                    if days_held >= 1 and cur >= sc["tp"]:
                        reason = "tp"
                    elif days_held >= 1 and cur <= sc["sl"]:
                        reason = "sl"
                    elif days_held >= 3 and (pos.get("side") == "put"
                                             and smc_helper_regime.trend_htf(data[pos["symbol"]][data[pos["symbol"]].index.normalize() <= d]) == "bull"):
                        reason = "trend_reversal"
                    if reason:
                        pnl = val - entry_net
                        if sc.get("comision"):
                            pnl -= 2.0 * sc["comision"] * 2
                        equity3 += pnl
                        trades3.append(dict(symbol=pos["symbol"], entry_date=pos["entry_date"],
                                            exit_date=d, entry_premium=entry_net,
                                            exit_value=val, pnl=pnl,
                                            pnl_pct=pnl / entry_net, reason=reason,
                                            days_held=days_held, motor="regime_aware"))
                        continue
                still3.append(pos)
            pos3 = still3

            sub_all = {}
            regime = "cash"
            bull_count, bear_count = 0, 0
            for sym in sc["tickers"]:
                dfsym = data.get(sym)
                if dfsym is None:
                    continue
                sub = dfsym[dfsym.index.normalize() <= d]
                if len(sub) < 110:
                    continue
                sub_all[sym] = sub
                r = rsi(sub["close"])
                s200 = sma(sub["close"], 200)
                is_bull = (pd.notna(r.iloc[-1]) and r.iloc[-1] > 50
                           and pd.notna(s200.iloc[-1])
                           and sub["close"].iloc[-1] > s200.iloc[-1])
                ch = None
                if len(sub) >= 60:
                    ch = put_choch_entry(sub, d)
                if is_bull:
                    bull_count += 1
                if ch and ch.get("type") == "put_choch":
                    bear_count += 1
            n = len(sub_all)
            if bear_count >= n * 0.3:
                regime = "bear"
            elif bull_count >= n * 0.5:
                regime = "bull"
            else:
                regime = "cash"

            if regime == "bull" and d >= next_rebal:
                for p in pos3:
                    if p.get("side") == "equity":
                        rows = data[p["symbol"]][data[p["symbol"]].index.normalize() == d]
                        if len(rows):
                            val = (p["entry_net"] * float(rows["close"].iloc[-1])
                                   / _ref_spot(p))
                            pnl = val - p["entry_net"]
                            equity3 += pnl
                            trades3.append(dict(symbol=p["symbol"], entry_date=p["entry_date"],
                                                exit_date=d, pnl=pnl, pnl_pct=pnl/p["entry_net"],
                                                reason="rebalance", motor="regime_aware",
                                                days_held=(d-p["entry_date"]).days))
                pos3 = [p for p in pos3 if p.get("side") != "equity"]
                # Al rebalancear solo se cierran las patas de acciones; los put
                # spreads abiertos siguen ocupando capital. Repartir el equity
                # ENTERO entre las acciones sobrecomprometía la cuenta (podía
                # comprometer puts + 100% del equity) y la dejaba en negativo
                # si todo perdía. Se reparte solo lo que queda libre.
                comprometido_puts = sum(p["entry_net"] for p in pos3
                                        if p.get("side") != "equity")
                per = _safe_per_symbol(equity3, len(rebal_syms), sc,
                                       committed=comprometido_puts)
                for sym in (rebal_syms if per > _MIN_PER else []):
                    dfsym = data.get(sym)
                    if dfsym is None:
                        continue
                    rows = dfsym[dfsym.index.normalize() == d]
                    if len(rows):
                        _px = float(rows["close"].iloc[-1])
                        pos3.append(dict(symbol=sym, side="equity",
                                         entry_net=equity_entry_cost(per, sc),
                                         last_spot=_px, entry_spot=_px,
                                         entry_date=d, spread=None))
                next_rebal = d + pd.Timedelta(days=7)
            elif regime == "bear" and len(pos3) < sc["max_pos"]:
                # abrir puts en tickers con CHoCH bear
                for sym in sc["tickers"]:
                    if any(p["symbol"] == sym and p.get("side") == "put"
                           for p in pos3):
                        continue
                    sub = sub_all.get(sym)
                    if sub is None:
                        continue
                    if put_choch_entry(sub, d) is None:
                        continue
                    spot = sub["close"].iloc[-1]
                    rv = realized_vol(sub)
                    spread = build_spread(spot, rv or 0.3, d, sc, side="put")
                    if spread is None:
                        continue
                    risk_budget = equity3 * sc["risk_pct"]
                    entry_net = option_entry_cost(spread, sc)
                    committed3 = sum(p["entry_net"] for p in pos3)
                    available3 = equity3 - committed3
                    if equity3 <= 0 or available3 <= 0:
                        continue
                    if entry_net + _roundtrip_commission(sc) > min(
                            risk_budget + _roundtrip_commission(sc), available3):
                        continue
                    pos3.append(dict(symbol=sym, side="put", spread=spread,
                                     entry_net=entry_net, last_spot=spot,
                                     entry_date=d))
                    break
            ec3.append(dict(date=d, equity=round(equity3, 2), open_positions=len(pos3)))
        # cerrar al final
        for pos in pos3:
            exit_rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == dates[-1]]
            exit_spot = float(exit_rows["close"].iloc[-1]) if len(exit_rows) else pos["last_spot"]
            if pos.get("side") == "equity":
                val = pos["entry_net"] * exit_spot / _ref_spot(pos)
            else:
                val = option_exit_value(pos["spread"], pos["last_spot"],
                                        (dates[-1] - pos["entry_date"]).days,
                                        sc, exit_spot=exit_spot)
            pnl = val - pos["entry_net"]
            if pos.get("side") != "equity" and sc.get("comision"):
                pnl -= 2.0 * sc["comision"] * 2
            equity3 += pnl
            trades3.append(dict(symbol=pos["symbol"], entry_date=pos["entry_date"],
                                exit_date=dates[-1], entry_premium=pos["entry_net"],
                                exit_value=val, pnl=pnl, reason="fin_backtest",
                                motor="regime_aware"))
        equity, trades, equity_curve = equity3, trades3, ec3
    if sc["motor"] == "regime_hold_cash":
        # Variante: bull => hold semanal equally weighted; bear => cash;
        # lateral => cash. Sin puts (las comisiones las dejan en break-even).
        equity3b = CAPITAL_INICIAL
        pos3b, trades3b, ec3b = [], [], []
        next_rebalb = dates[0]
        rebal_symsb = sorted(sc["tickers"])[:sc["max_pos"]]
        crash_lockb = None  # día en que se activó el crash event (cool-down)
        for d in dates:
            # --- Defensa INTRADIARIA (hallazgo18): si el precio del día
            # rompe X% bajo el close previo (low del día), el rebalance del
            # mismo día usa el precio de quiebre (ejecución intradiaria) en
            # vez del close. Esto modela un stop/trailing stop que corta
            # dentro del día, antes del cierre, y evita que un rebalance
            # comprado en día de crash "herede" la pérdida al recomprar.
            intraday_cutb = {}
            if sc.get("intraday_stop"):
                ith = sc["intraday_stop"]
                for sym in sc["tickers"]:
                    dfsym = data.get(sym)
                    if dfsym is None or len(dfsym) < 2:
                        continue
                    sub = dfsym[dfsym.index.normalize() <= d]
                    if len(sub) < 2:
                        continue
                    low_today = float(sub["low"].iloc[-1])
                    close_prev = float(sub["close"].iloc[-2])
                    if low_today <= (1 - ith) * close_prev:
                        # precio de quiebre (best case: fill inmediato)
                        intraday_cutb[sym] = (1 - ith) * close_prev
            # cerrar rebalance del hold
            if d >= next_rebalb:
                for p in pos3b:
                    rows = data[p["symbol"]][data[p["symbol"]].index.normalize() == d]
                    if len(rows):
                        exit_spot = float(rows["close"].iloc[-1])
                        if p["symbol"] in intraday_cutb:
                            exit_spot = intraday_cutb[p["symbol"]]
                        val = equity_exit_value(p["entry_net"], exit_spot, _ref_spot(p), sc)
                        pnl = val - p["entry_net"]
                        if sc.get("comision"):
                            pnl -= sc["comision"]
                        equity3b += pnl
                        trades3b.append(dict(symbol=p["symbol"], entry_date=p["entry_date"],
                                             exit_date=d, pnl=pnl, pnl_pct=pnl / p["entry_net"],
                                             reason="rebalance", motor="regime_hold_cash",
                                             days_held=(d - p["entry_date"]).days))
                pos3b = []
                per = _safe_per_symbol(equity3b, len(rebal_symsb), sc)
                for sym in (rebal_symsb if per > _MIN_PER else []):
                    dfsym = data.get(sym)
                    if dfsym is None:
                        continue
                    rows = dfsym[dfsym.index.normalize() == d]
                    if len(rows):
                        last_spot = float(rows["close"].iloc[-1])
                        if sym in intraday_cutb:
                            last_spot = intraday_cutb[sym]
                        pos3b.append(dict(symbol=sym,
                                          entry_net=equity_entry_cost(per, sc),
                                          last_spot=last_spot,
                                          entry_spot=last_spot,
                                          entry_date=d, motor="regime_hold_cash",
                                          side="equity"))
                next_rebalb = d + pd.Timedelta(days=7)
            # régimen
            regimeb = "cash"
            bull_countb, bear_countb = 0, 0
            n = 0
            # --- Detector de evento de crash (mitigación flash crash):
            # si un ticker pierde ≥ umbral desde su máx reciente de 5 velas en
            # ≤2 velas y ≥30% del universo lo muestra, cortar el hold a cash
            # de inmediato (antes del CHoCH, que requiere estructura previa).
            crash_event = False
            if sc.get("crash_event"):
                c_thresh = sc["crash_event"]  # ej. 0.08 = -8%
                n_crash = 0
                n_eval = 0
                for sym in sc["tickers"]:
                    dfsym = data.get(sym)
                    if dfsym is None:
                        continue
                    sub = dfsym[dfsym.index.normalize() <= d]
                    if len(sub) < 6:
                        continue
                    # Detección reactiva en el día del shock: comparar el open
                    # del día en curso contra el máximo de las 6 velas previas
                    # (excluyendo el día en curso). Un gap o apertura con
                    # caída acumulada >= umbral corta el hold ese mismo día
                    # (sin esperar al cierre). El rebalance del día 1 no es
                    # afectado porque el open == hi6 del mismo bloque...
                    # NO: para el día 1 open del shock == close previo == hi6
                    # por construcción del shock sintético, así que no cancela.
                    close_today = float(sub["close"].iloc[-1])
                    close_2d = float(sub["close"].iloc[-3]) if len(sub) >= 3 \
                        else close_today
                    n_eval += 1
                    # velocidad de caída 2 días (pánico intradiario)
                    fast = close_2d > 0 and close_today / close_2d - 1 \
                        <= -c_thresh
                    n_crash += 1 if fast else 0
                if n_eval > 0 and n_crash >= n_eval * 0.3:
                    crash_event = True
            # --- cool-down del detector: una vez activado, no puede
            # desactivarse hasta 5 días después, evitando que rebalances
            # re-entren y se corten el mismo día durante pánicos en fases
            if crash_event:
                crash_lockb = d
            elif crash_lockb is not None and (d - crash_lockb).days < 5:
                crash_event = True
            # fuerza de bull hasta una fecha (stress test): permite sostener
            # el hold hasta el día del shock sintético aunque la historia
            # previa ya sea bear por CHoCH. El detector crash_event permanece
            # activo dentro de la ventana de fuerza.
            forced_bull = bool(sc.get("force_bull_until") and d <= pd.Timestamp(
                sc["force_bull_until"], tz="UTC").normalize())
            if not forced_bull:
                for sym in sc["tickers"]:
                    dfsym = data.get(sym)
                    if dfsym is None:
                        continue
                    sub = dfsym[dfsym.index.normalize() <= d]
                    if len(sub) < 110:
                        continue
                    n += 1
                    r = rsi(sub["close"])
                    s200 = sma(sub["close"], 200)
                    if pd.notna(r.iloc[-1]) and r.iloc[-1] > 50 and pd.notna(s200.iloc[-1]) \
                            and sub["close"].iloc[-1] > s200.iloc[-1]:
                        bull_countb += 1
                    if len(sub) >= 60 and put_choch_entry(sub, d) is not None:
                        bear_countb += 1
            if bear_countb >= n * 0.3 or crash_event:
                regimeb = "bear"  # salir del hold (cash) en selloff
            elif bull_countb >= n * 0.5:
                regimeb = "bull"
            if regimeb == "bear" and pos3b:
                # cerrar el hold y quedarse en cash
                for p in pos3b:
                    rows = data[p["symbol"]][data[p["symbol"]].index.normalize() == d]
                    exit_spot = float(rows["close"].iloc[-1]) if len(rows) else p["last_spot"]
                    if p["symbol"] in intraday_cutb:
                        exit_spot = intraday_cutb[p["symbol"]]
                    val = equity_exit_value(p["entry_net"], exit_spot, _ref_spot(p), sc)
                    pnl = val - p["entry_net"]
                    if sc.get("comision"):
                        pnl -= sc["comision"]
                    equity3b += pnl
                    trades3b.append(dict(symbol=p["symbol"], entry_date=p["entry_date"],
                                         exit_date=d, pnl=pnl, pnl_pct=pnl / p["entry_net"],
                                         reason="bear_cash", motor="regime_hold_cash",
                                         days_held=(d - p["entry_date"]).days))
                pos3b = []
                next_rebalb = d + pd.Timedelta(days=7)
            ec3b.append(dict(date=d, equity=round(equity3b, 2), open_positions=len(pos3b)))
        equity, trades, equity_curve = equity3b, trades3b, ec3b
    if sc["motor"] == "hold_weekly" and is_hold:
        # benchmark justo: reequilibrio semanal, no diario (evita churn)
        equity2 = CAPITAL_INICIAL
        open_pos2, trades2, ec2 = [], [], []
        next_rebal = dates[0]
        rebal_syms = sorted(sc["tickers"])[:sc["max_pos"]]
        for d in dates:
            if d >= next_rebal:
                for p in open_pos2:
                    rows = data[p["symbol"]][data[p["symbol"]].index.normalize() == d]
                    if len(rows):
                        exit_spot = float(rows["close"].iloc[-1])
                        val = equity_exit_value(p["entry_net"], exit_spot, _ref_spot(p), sc)
                        pnl = val - p["entry_net"]
                        if sc.get("comision"):
                            pnl -= sc["comision"]
                        equity2 += pnl
                        trades2.append(dict(symbol=p["symbol"], entry_date=p["entry_date"],
                                            exit_date=d, pnl=pnl, pnl_pct=pnl/p["entry_net"],
                                            reason="rebalance",
                                            days_held=(d-p["entry_date"]).days,
                                            motor="hold_weekly"))
                open_pos2 = []
                per = _safe_per_symbol(equity2, len(rebal_syms), sc)
                for sym in (rebal_syms if per > _MIN_PER else []):
                    dfsym = data.get(sym)
                    if dfsym is None:
                        continue
                    rows = dfsym[dfsym.index.normalize() == d]
                    if len(rows):
                        _px2 = float(rows["close"].iloc[-1])
                        open_pos2.append(dict(symbol=sym,
                                              entry_net=equity_entry_cost(per, sc),
                                              last_spot=_px2, entry_spot=_px2,
                                              entry_date=d, motor="hold_weekly",
                                              side="equity"))
                next_rebal = d + pd.Timedelta(days=7)
            still = []
            for pos in open_pos2:
                rows = data[pos["symbol"]][data[pos["symbol"]].index.normalize() == d]
                if len(rows):
                    pos["last_spot"] = float(rows["close"].iloc[-1])
                still.append(pos)
            open_pos2 = still
            ec2.append(dict(date=d, equity=round(equity2, 2), open_positions=len(open_pos2)))
        for p in open_pos2:
            rows = data[p["symbol"]][data[p["symbol"]].index.normalize() == dates[-1]]
            if len(rows):
                exit_spot = float(rows["close"].iloc[-1])
                val = equity_exit_value(p["entry_net"], exit_spot, _ref_spot(p), sc)
            else:
                val = p["entry_net"]
            pnl = val - p["entry_net"]
            if sc.get("comision"):
                pnl -= sc["comision"]
            equity2 += pnl
            trades2.append(dict(symbol=p["symbol"], entry_date=p["entry_date"],
                                exit_date=dates[-1], pnl=pnl,
                                reason="fin_backtest", days_held=(dates[-1]-p["entry_date"]).days,
                                motor="hold_weekly"))
        equity, trades, equity_curve = equity2, trades2, ec2

    for pos in open_pos:
        days_held = (dates[-1] - pos["entry_date"]).days
        exit_df = data[pos["symbol"]]
        exit_rows = exit_df[exit_df.index.normalize() == dates[-1]]
        exit_spot = float(exit_rows["close"].iloc[-1]) if len(exit_rows) else pos["last_spot"]
        if pos.get("side") == "equity":
            val = equity_exit_value(pos["entry_net"], exit_spot, _ref_spot(pos), sc)
        else:
            val = option_exit_value(pos["spread"], pos["last_spot"], days_held,
                                    sc, exit_spot=exit_spot)
        pnl = val - pos["entry_net"]
        if pos.get("side") != "equity" and sc.get("comision"):
            pnl -= 2.0 * sc["comision"] * 2  # 2 patas × $0.65, entr+sal
        equity += pnl
        trades.append(dict(symbol=pos["symbol"], entry_date=pos["entry_date"],
                           exit_date=dates[-1], entry_premium=pos["entry_net"],
                           exit_value=val, pnl=pnl, pnl_pct=pnl / pos["entry_net"],
                           reason="fin_backtest", days_held=days_held,
                           motor=pos["motor"]))

    tdf = pd.DataFrame(trades)
    ecdf = pd.DataFrame(equity_curve)
    dd_pct, max_eq = 0.0, CAPITAL_INICIAL
    if len(ecdf):
        ecdf["peak"] = ecdf["equity"].cummax()
        dd_pct = (ecdf["equity"] / ecdf["peak"] - 1).min() * 100
        max_eq = ecdf["equity"].max()
    return equity, tdf, ecdf, dd_pct, max_eq



# --- Ronda 10: datos recientes 2026 (abr-ago) para afinar estrategia regime-aware
# Contexto: SPX en máximos históricos (13-ago-2026), rally tech (+15% YTD), caída
# tech de jun-jul (-15-25%) seguida de rebote fuerte. Ventanas claves:
#  - abr-jul 2026: selloff tech (PLTR/TSLA/AMD -25% desde máx) → ideal para puts
#  - jul-ago 2026: rebote/rally → ideal para calls y hold
#  - abr-ago completo: ciclo completo rally→caída→rebote → prueba regime-aware real
SCENARIOS.update({
    "S72": dict(name="S36 rally reciente (jun-ago)", motor="smc_daily",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65),
    "S73": dict(name="Calls rebote (dip+RSI<25, mar-jul)", motor="rebote_rsi",
                window_dates=("2026-03-01", "2026-07-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65),
    "S74": dict(name="Hold semanal reciente (abr-ago)", motor="hold_weekly",
                window_dates=("2026-04-01", "2026-08-14"),
                tickers=UNI_RETO, risk_pct=0.25, max_pos=8, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S75": dict(name="Regime-aware reciente completo", motor="regime_aware",
                window_dates=("2026-04-01", "2026-08-14"),
                tickers=UNI_RETO, risk_pct=0.30, max_pos=2, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                cheap_min_net=28.0),
    "S76": dict(name="Regime-aware ticks baratos selloff tech",
                motor="regime_aware",
                window_dates=("2026-05-01", "2026-07-01"),
                tickers=["SOFI", "F", "NOK", "BB"], risk_pct=0.30, max_pos=2,
                dte=21, delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                cheap_min_net=28.0),
    "S77": dict(name="Hold tech pesado rebote (jun-ago)", motor="hold_weekly",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=UNI_TECH, risk_pct=0.25, max_pos=8, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S78": dict(name="Regime bull→hold, bear→cash (sin puts caras)",
                motor="regime_hold_cash",
                window_dates=("2026-04-01", "2026-08-14"),
                tickers=UNI_RETO, risk_pct=0.25, max_pos=8, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=False),
    "S79": dict(name="Calls dip-SPY: rebote post-crash jun", motor="rebote_rsi",
                window_dates=("2026-06-01", "2026-07-15"),
                tickers=["TQQQ", "TSLA", "AMD", "PLTR", "NVDA"],
                risk_pct=0.15, max_pos=3, dte=14,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65),
    "S80": dict(name="Walk-forward reciente: 30d + 30d",
                motor="smc_daily", window_days=60,
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65),
    # --- Ronda 10b: rebote refinado (umbrales permisivos + giro SMA5)
    "S81": dict(name="Rebote RSI30/28 mar-jul", motor="rebote_rsi_v2",
                window_dates=("2026-03-01", "2026-07-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                rsi_floor=30, rsi_cross=28, dip_pct=0.85),
    "S82": dict(name="Rebote RSI30/28 ciclo completo", motor="rebote_rsi_v2",
                window_dates=("2026-04-01", "2026-08-14"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                rsi_floor=30, rsi_cross=28, dip_pct=0.85),
    "S83": dict(name="Rebote giro SMA5 mar-jul", motor="rebote_sma5",
                window_dates=("2026-03-01", "2026-07-01"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                dip_pct=0.85),
    "S84": dict(name="Rebote giro SMA5 tech pesado jun-ago",
                motor="rebote_sma5",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=["TQQQ", "TSLA", "AMD", "PLTR", "NVDA"],
                risk_pct=0.15, max_pos=3, dte=14,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                dip_pct=0.85),
})


# --- Ronda 10b: refinamiento rebote_rsi (los mínimos RSI 2026 fueron 25-33,
# el umbral 25 nunca cruza). Pruebas con umbrales permisivos y dip+crucSMA5.
def rebote_rsi_entry_v2(hist, d, rsi_floor=30, rsi_cross=28, dip_pct=0.85):
    """Dip >=15% del máx 60d y RSI cruza alcista el umbral de oversold."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 80:
        return None
    win60 = sub["close"].iloc[-60:]
    hi = win60.max()
    r = rsi(sub["close"])
    close_now = sub["close"].iloc[-1]
    if close_now > hi * dip_pct:
        return None
    rsi_now = r.iloc[-1]
    if pd.isna(rsi_now):
        return None
    if rsi_now >= rsi_cross and r.iloc[-2] < rsi_cross:
        return dict(type="rebote_rsi_v2")
    return None


def rebote_sma5_entry(hist, d, dip_pct=0.85):
    """Dip >=15% del máx 60d y el cierre cruza por encima de SMA5
    (señal de giro mecánica, no depende de RSI)."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 65:
        return None
    win60 = sub["close"].iloc[-60:]
    hi = win60.max()
    close_now = sub["close"].iloc[-1]
    if close_now > hi * dip_pct:
        return None
    s5 = sma(sub["close"], 5)
    if pd.isna(s5.iloc[-1]) or pd.isna(s5.iloc[-2]):
        return None
    if close_now > s5.iloc[-1] and sub["close"].iloc[-2] <= s5.iloc[-2]:
        return dict(type="rebote_sma5")
    return None


def rebote_exit_rsi60(hist, d, top=60):
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 60:
        return False
    return bool(pd.notna(rsi(sub["close"]).iloc[-1])
                and rsi(sub["close"]).iloc[-1] > top)


MOTORES["rebote_rsi_v2"] = (rebote_rsi_entry_v2, rebote_exit_rsi60)
MOTORES["rebote_sma5"] = (rebote_sma5_entry, rebote_exit_rsi60)


# --- Ronda 10c: rebote calibrado al mercado 2026 (RSI 30-50 en dips, no oversold)
def rebote_rsi40_entry(hist, d, dip_pct=0.88):
    """Dip >=12% del máx 60d y RSI14 cruza alcista por encima de 40.
    Calibrado a los rebotes reales de jun-jul 2026 (RSI mín 25-42)."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 80:
        return None
    win60 = sub["close"].iloc[-60:]
    hi = win60.max()
    close_now = sub["close"].iloc[-1]
    if close_now > hi * dip_pct:
        return None
    r = rsi(sub["close"])
    rsi_now = r.iloc[-1]
    if pd.isna(rsi_now):
        return None
    if rsi_now >= 40 and r.iloc[-2] < 40:
        return dict(type="rebote_rsi40")
    return None


MOTORES["rebote_rsi40"] = (rebote_rsi40_entry, rebote_exit_rsi60)

SCENARIOS.update({
    "S85": dict(name="Rebote RSI40 calibrado jun-jul", motor="rebote_rsi40",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                dip_pct=0.88),
    "S86": dict(name="Rebote RSI40 tech pesado jun-ago", motor="rebote_rsi40",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=["TQQQ", "TSLA", "AMD", "PLTR", "NVDA"],
                risk_pct=0.15, max_pos=3, dte=21,
                delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                dip_pct=0.88),
})


# --- Ronda 10d: rebote en tickers baratos (spreads viables con $100)
SCENARIOS.update({
    "S87": dict(name="Rebote RSI40 tickers baratos jun-ago", motor="rebote_rsi40",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=["SOFI", "F", "NOK", "BB"], risk_pct=0.15, max_pos=3,
                dte=21, delta_l=0.30, delta_s=0.10, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                dip_pct=0.88),
    "S88": dict(name="Rebote RSI40 OTM 0.25/0.08 jun-ago", motor="rebote_rsi40",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=UNI_RETO, risk_pct=0.15, max_pos=3,
                dte=21, delta_l=0.25, delta_s=0.08, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                dip_pct=0.88),
    "S89": dict(name="Rebote RSI40 OTM baratos risk 30%", motor="rebote_rsi40",
                window_dates=("2026-06-01", "2026-08-14"),
                tickers=["SOFI", "F", "NOK", "BB"], risk_pct=0.30, max_pos=3,
                dte=21, delta_l=0.25, delta_s=0.08, tp=1.5, sl=0.5,
                max_rv=None, anti_earnings=True, comision=0.65,
                dip_pct=0.88),
})

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    all_tickers = sorted({t for s in SCENARIOS.values() for t in s["tickers"]})
    cache_path = os.environ.get("BT_CACHE")
    if cache_path and os.path.exists(cache_path):
        # Dataset congelado en disco (download_bt_cache.py): mismo histórico
        # para todos los escenarios y corridas reproducibles sin depender de
        # la red ni del rango SIP de Alpaca.
        import pickle
        with open(cache_path, "rb") as f:
            data = pickle.load(f)
        print(f"Cache {cache_path}: {len(data)} tickers")
    else:
        feed = MarketDataFeed(os.environ.get("DATA_PROVIDER", "yfinance"))
        print(f"Descargando {N_DIAS_HIST}d para {len(all_tickers)} tickers...")
        t0 = time.time()
        data = feed.history(all_tickers, "1d", days=N_DIAS_HIST)
        print(f"Datos listos en {time.time()-t0:.0f}s")

    rows = []
    out_dir = os.environ.get("BT_OUT", "/home/ubuntu/backtests")
    os.makedirs(out_dir, exist_ok=True)
    keys = [args.scenario] if args.scenario else (list(SCENARIOS) if args.all else ["S1"])
    for key in keys:
        sc = SCENARIOS[key]
        t0 = time.time()
        equity, tdf, ecdf, dd_pct, max_eq = run_scenario(key, sc, data)
        elapsed = time.time() - t0
        wr = (tdf["pnl"].gt(0).mean() * 100) if len(tdf) else 0.0
        rows.append(dict(scenario=key, name=sc["name"], motor=sc["motor"],
                         window_days=sc.get("window_days") or "n/a (fechas)",
                         tickers=",".join(sc["tickers"]),
                         risk_pct=sc["risk_pct"], max_pos=sc["max_pos"],
                         dte=sc["dte"], delta=f"{sc['delta_l']}/{sc['delta_s']}",
                         tp=sc["tp"], sl=sc["sl"],
                         max_rv=sc.get("max_rv"),
                         anti_earnings=sc.get("anti_earnings", False),
                         equity_final=round(equity, 2),
                         retorno_pct=round((equity / CAPITAL_INICIAL - 1) * 100, 1),
                         trades=len(tdf), wins=int((tdf["pnl"] > 0).sum()) if len(tdf) else 0,
                         win_rate=round(wr, 0),
                         pnl_total=round(tdf["pnl"].sum(), 2) if len(tdf) else 0,
                         max_drawdown_pct=round(dd_pct, 1),
                         max_equity=round(max_eq, 2),
                         segundos=round(elapsed, 0)))
        if len(tdf):
            tdf.to_csv(f"{out_dir}/bt_{key}_trades.csv", index=False)
        if len(ecdf):
            ecdf.to_csv(f"{out_dir}/bt_{key}_equity.csv", index=False)
        print(f"[{key}] {sc['name']}: ${equity:.2f} ({(equity/CAPITAL_INICIAL-1)*100:+.1f}%) "
              f"| trades={len(tdf)} wr={wr:.0f}% dd={dd_pct:.1f}% | {elapsed:.0f}s")

    rdf = pd.DataFrame(rows)
    rdf.to_csv(f"{out_dir}/bt_resumen.csv", index=False)
    print("\n=== RESUMEN ===")
    print(rdf.to_string(index=False))


if __name__ == "__main__":
    main()







# ---------------------------------------------------------------------------
# Pata de REBOTE documentada (docs/skills/wheel_skill.md §4)
# El skill describe S36 como "Rebote en selloff (RSI<25, precio>SMA100) ->
# call spread 0.30/0.10, DTE 21, budget 15%", con +53-60% y win 71-75%. Pero
# en el codigo S36 es motor="smc_daily": la condicion documentada NO existia
# como motor. Se implementa aqui tal cual la describe la documentacion, para
# poder medirla en vez de citarla.
# ---------------------------------------------------------------------------
def rebote_doc_entry(hist, d, rsi_max=25.0, sma_floor=100):
    """RSI14 < rsi_max con el precio por encima de la SMA(sma_floor).

    La logica: sobreventa fuerte (RSI<25) pero estructura de fondo intacta
    (sigue sobre la SMA100), o sea un retroceso dentro de tendencia y no un
    cambio de tendencia. Anti-look-ahead: solo filas <= d.
    """
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < sma_floor + 20:
        return None
    r = rsi(sub["close"])
    sf = sma(sub["close"], sma_floor)
    last_close = float(sub["close"].iloc[-1])
    if pd.isna(r.iloc[-1]) or pd.isna(sf.iloc[-1]):
        return None
    if r.iloc[-1] < rsi_max and last_close > float(sf.iloc[-1]):
        return dict(type="rebote_doc")
    return None


def rebote_doc_exit(hist, d, rsi_out=60.0):
    """Salida del rebote: RSI recuperado por encima de rsi_out."""
    sub = hist[hist.index.normalize() <= d]
    if len(sub) < 30:
        return False
    r = rsi(sub["close"])
    return bool(pd.notna(r.iloc[-1]) and r.iloc[-1] > rsi_out)


MOTORES["rebote_doc"] = (rebote_doc_entry, rebote_doc_exit)
