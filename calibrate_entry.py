"""Calibración de entrada paper — viernes 14 ago 2026.

Extrae chains de opciones (yfinance, feed de Alpaca en producción) para F,
TQQQ y NOK y lista spreads debit call que cumplen el perfil reto:
  delta long ~0.25, delta short ~0.10, DTE 10-45 (preferir 30-45 para
  amortiguar gamma de fin de semana), prima neta máx $12.
Usa la API pública de Alpaca (trading API) para obtener el stream de datos
de opciones si hay credenciales; si no, usa yfinance como respaldo.
"""
import os
import datetime as dt
import pandas as pd

pd.set_option("display.width", 250)

import yfinance as yf

SPOT = {}
CANDIDATES = ["F", "TQQQ", "NOK"]

try:
    import requests as _rq
    key = os.environ.get("APCA_API_KEY_ID")
    secret = os.environ.get("APCA_API_SECRET_KEY")
    if not key or not secret:
        raise RuntimeError("credenciales Alpaca ausentes; usar yfinance")
    for t in CANDIDATES:
        r = _rq.get(f"https://data.alpaca.markets/v1beta1/stocks/{t}/snapshots",
                    headers={"APCA-API-KEY-ID": key,
                             "APCA-API-SECRET-KEY": secret}, timeout=15)
        r.raise_for_status()
        j = r.json()
        snap = j.get("snapshots", {}).get(t) or {}
        lt = snap.get("latestTrade") or {}
        if lt.get("p"):
            SPOT[t] = round(lt["p"], 2)
        else:
            raise RuntimeError("sin trade")
    print("Spots (Alpaca paper REST):", SPOT)
except Exception as e:
    print("Alpaca fallback:", e)
    d = yf.download(CANDIDATES, period="2d", interval="1d",
                    group_by="ticker", progress=False)
    for t in CANDIDATES:
        try:
            SPOT[t] = round(float(d[t]["Close"].iloc[-1]), 2)
        except Exception:
            pass
    print("Spots (yfinance):", SPOT)

for ticker in CANDIDATES:
    if ticker not in SPOT:
        print(f"\n{ticker}: sin spot, saltando")
        continue
    spot = SPOT[ticker]
    print(f"\n=== {ticker} spot=${spot} ===")
    TODAY = dt.date.today()
    try:
        o = yf.Ticker(ticker)
        chain = o.options
    except Exception as e:
        print(f"\n{ticker}: error opciones {e}")
        continue
    from math import log, sqrt, exp
    from statistics import NormalDist

    def bs_delta(s, k, t, iv, r=0.04):
        if t <= 0 or iv <= 0:
            return None
        d1 = (log(s / k) + (r + iv * iv / 2) * t) / (iv * sqrt(t))
        return NormalDist().cdf(d1)

    rows = []
    for expiry in chain:
        ed = dt.date.fromisoformat(expiry)
        dte = (ed - TODAY).days
        if dte < 10 or dte > 45:
            continue
        try:
            c = o.option_chain(expiry)
        except Exception:
            continue
        calls = c.calls
        for _, r in calls.iterrows():
            if r.bid == 0 or r.ask == 0:
                continue
            mid = (r.bid + r.ask) / 2
            d = bs_delta(spot, r.strike, dte / 365.0, r.impliedVolatility or 0.5)
            rows.append({
                "exp": exp, "dte": dte, "strike": r.strike,
                "bid": r.bid, "ask": r.ask, "mid": mid,
                "iv": r.impliedVolatility or 0,
                "delta": d if d is not None else 0,
                "oi": r.openInterest or 0,
                "vol": r.volume or 0,
            })
    df = pd.DataFrame(rows)
    if df.empty:
        print(f"\n{ticker}: sin strikes válidos 10-45 DTE")
        continue
    df = df.sort_values("dte")
    # Long: delta ~0.25 (call ITM/ATM), short: delta ~0.10 (OTM)
    longs = df[df["delta"] >= 0.20]
    shorts = df[df["delta"] <= 0.15]
    print(f"  Longs (delta>=0.20): {len(longs)} | Shorts (delta<=0.15): {len(shorts)}")
    best = []
    for _, lg in longs.iterrows():
        for _, sh in shorts.iterrows():
            if sh.dte != lg.dte or sh.strike <= lg.strike:
                continue
            if abs(sh.dte - 40) > 5:  # preferir ~40 DTE
                continue
            net = lg.mid - sh.mid
            if net <= 0 or net > 12.0:
                continue
            best.append({
                "lg_strike": lg.strike, "lg_delta": lg.delta,
                "sh_strike": sh.strike, "sh_delta": sh.delta,
                "exp": lg.exp, "dte": lg.dte, "net_mid": net,
                "lg_iv": lg.iv, "lg_oi": lg.oi, "sh_oi": sh.oi,
            })
    if not best:
        # Relajar DTE si no hay 35-45
        for _, lg in longs.iterrows():
            for _, sh in shorts.iterrows():
                if sh.dte != lg.dte or sh.strike <= lg.strike:
                    continue
                net = lg.mid - sh.mid
                if net <= 0 or net > 12.0:
                    continue
                best.append({
                    "lg_strike": lg.strike, "lg_delta": lg.delta,
                    "sh_strike": sh.strike, "sh_delta": sh.delta,
                    "exp": lg.exp, "dte": lg.dte, "net_mid": net,
                    "lg_iv": lg.iv, "lg_oi": lg.oi, "sh_oi": sh.oi,
                })
    if best:
        best.sort(key=lambda x: -x["dte"])
        out = pd.DataFrame(best)
        print(out.head(10).to_string(index=False))
    else:
        print("  sin spreads debit que cumplan prima neta <= $12")
        print("  mejores longs:", df[df.delta >= 0.22]
              .sort_values("dte").head(6)[["exp", "dte", "strike", "delta",
                                           "bid", "ask", "mid", "oi"]].to_string(index=False))

