"""Calibración fina de la entrada. El perfil reto pide delta long ~0.25; el
output anterior mostraba deep-ITM (delta 0.95) porque el long con mayor delta
dominaba la prima neta. Aquí filtro: long 0.25-0.50, short <= 0.15, DTE 30-45,
prima neta <= $12, y priorizo OI alto en ambas patas (liquidez en paper Alpaca).
"""
import os
import datetime as dt
import requests
import pandas as pd
import yfinance as yf
from math import log, sqrt
from statistics import NormalDist

pd.set_option("display.width", 250)

CANDIDATES = ["F", "TQQQ", "NOK"]
key = os.environ.get("APCA_API_KEY_ID", "PK6NXQZR54PK7DKCFEM7U3ULNE")
secret = os.environ.get("APCA_API_SECRET_KEY",
                        "8HqWabPkVeWgig67o9topXdo6y65scrVuvVyoPK4Jkj5")


def get_spot(t):
    try:
        r = requests.get("https://data.alpaca.markets/v2/stocks/snapshots",
                         params={"symbols": t},
                         headers={"APCA-API-KEY-ID": key,
                                  "APCA-API-SECRET-KEY": secret}, timeout=15)
        r.raise_for_status()
        j = r.json()
        snap = j.get(t, {})
        lt = snap.get("latestTrade") or snap.get("dailyBar") or {}
        return round(lt.get("p", 0), 2)
    except Exception:
        d = yf.download(t, period="2d", interval="1d", progress=False)
        return round(float(d["Close"].iloc[-1]), 2)


def bs_delta(s, k, t, iv, r=0.04):
    if t <= 0 or iv <= 0:
        return None
    d1 = (log(s / k) + (r + iv * iv / 2) * t) / (iv * sqrt(t))
    return NormalDist().cdf(d1)


TODAY = dt.date.today()

all_rows = []
for t in CANDIDATES:
    spot = get_spot(t)
    print(f"{t}: spot=${spot}")
    o = yf.Ticker(t)
    for exp in o.options:
        ed = dt.date.fromisoformat(exp)
        dte = (ed - TODAY).days
        if dte < 30 or dte > 45:
            continue
        try:
            calls = o.option_chain(exp).calls
        except Exception:
            continue
        for _, r in calls.iterrows():
            if not r.bid or not r.ask:
                continue
            d = bs_delta(spot, r.strike, dte / 365.0,
                         r.impliedVolatility or 0.5)
            if d is None:
                continue
            all_rows.append({
                "ticker": t, "spot": spot, "exp": exp, "dte": dte,
                "strike": r.strike, "bid": r.bid, "ask": r.ask,
                "mid": (r.bid + r.ask) / 2, "iv": r.impliedVolatility or 0,
                "delta": d, "oi": r.openInterest or 0,
            })

df = pd.DataFrame(all_rows)

print("\nSpreads debit calibrados (long 0.25-0.50 delta, short <=0.15):")
found = []
for t in CANDIDATES:
    dft = df[df.ticker == t]
    longs = dft[(dft.delta >= 0.25) & (dft.delta <= 0.50)]
    shorts = dft[dft.delta <= 0.15]
    for _, lg in longs.iterrows():
        for _, sh in shorts.iterrows():
            if sh.exp != lg.exp or sh.strike <= lg.strike:
                continue
            net = lg.mid - sh.mid
            if net <= 0 or net > 12.0:
                continue
            max_loss = net  # debit spread: riesgo máx = prima neta
            if lg.oi < 50:
                continue
            found.append({
                "ticker": t, "lg": f"C{lg.strike}", "sh": f"C{sh.strike}",
                "lg_delta": round(lg.delta, 2),
                "sh_delta": round(sh.delta, 2),
                "exp": lg.exp, "dte": lg.dte,
                "net_mid": round(net, 2),
                "net_ask": round((lg.ask - sh.bid), 2),
                "max_loss": round(net, 2),
                "breakeven": round(lg.strike + net, 2),
                "spot": lg.spot,
                "lg_oi": lg.oi, "sh_oi": sh.oi,
            })

if found:
    out = pd.DataFrame(found).sort_values(["ticker", "net_mid"])
    print(out.to_string(index=False))
else:
    print("sin resultados con OI>=50; relajando OI:")
    for t in CANDIDATES:
        dft = df[df.ticker == t]
        longs = dft[(dft.delta >= 0.25) & (dft.delta <= 0.50)]
        shorts = dft[dft.delta <= 0.15]
        print(f"\n{t}: longs 0.25-0.50 delta:")
        print(longs.sort_values("strike")[[
            "exp", "strike", "delta", "bid", "ask", "mid", "iv", "oi"]
        ].head(12).to_string(index=False))
