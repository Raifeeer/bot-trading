"""Cotiza las patas del spread TQQQ C85/C100 2026-09-18 en Alpaca paper
para fijar el límite de la orden. Endpoint: /v1beta1/options/snapshots
(con credentials de trading; data feed paper incluye snapshots de opciones).
"""
import os
import requests
import json

key = os.environ.get("APCA_API_KEY_ID", "PK6NXQZR54PK7DKCFEM7U3ULNE")
secret = os.environ.get("APCA_API_SECRET_KEY",
                        "8HqWabPkVeWgig67o9topXdo6y65scrVuvVyoPK4Jkj5")
h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}

# Descubrir el endpoint correcto por intento
candidates = [
    ("https://data.alpaca.markets/v1beta1/options/snapshots",
     {"symbols": "TQQQ260918C00085000,TQQQ260918C00100000"}),
    ("https://data.alpaca.markets/v1beta1/options/TQQQ/snapshots", None),
    ("https://data.alpaca.markets/v2/options/snapshots",
     {"symbols": "TQQQ260918C00085000,TQQQ260918C00100000"}),
]
for url, params in candidates:
    try:
        r = requests.get(url, headers=h, params=params, timeout=15)
        print(f"--- {url} params={params} -> {r.status_code}")
        if r.status_code == 200:
            j = r.json()
            print(json.dumps(j, indent=1)[:2000])
            break
    except Exception as e:
        print(f"--- {url} ERROR {e}")

# Además probar el stream REST de trades de opciones (v1beta2)
for path in ["/v1beta2/options/trades/latest",
             "/v1beta1/options/trades/latest"]:
    try:
        r = requests.get(f"https://data.alpaca.markets{path}",
                         headers=h, timeout=15,
                         params={"symbols": "TQQQ260918C00085000"})
        print(f"--- {path} -> {r.status_code}")
        if r.status_code == 200:
            print(json.dumps(r.json(), indent=1)[:1500])
    except Exception as e:
        print(f"--- {path} ERROR {e}")
