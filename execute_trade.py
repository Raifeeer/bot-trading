"""Ejecuta el spread vertical call TQQQ 85/100 Sep-18-2026 en Alpaca paper.

Usa una orden MULTI-LEG (leg_in_strategy: vertical spread) vía
POST /v2/trades?strategy=debit, si la API paper lo soporta; si no,
abre las dos patas por separado (BUY +10 C85, SELL -10 C100) y registra
el spread manualmente.

Límite: prima neta <= $1.97 (mid actual 2.18-0.44=1.74 de bp... usar mid
neto de quotes reales: bp 2.18 + ap 0.44 = 2.62 neto ask... El neto real
usando bp del long (2.18) y ap del short (0.44) es comprar al peor bid-ask:
neto = 2.18 + 0.44 = 2.62. Mid neto = (2.36+2.18)/2 - (0.44+0.34)/2 = 2.27
- 0.39 = 1.88. Límite prudente: $1.90 por contrato.
"""
import os
import json
import requests

key = os.environ.get("APCA_API_KEY_ID", "PK6NXQZR54PK7DKCFEM7U3ULNE")
secret = os.environ.get("APCA_API_SECRET_KEY",
                        "8HqWabPkVeWgig67o9topXdo6y65scrVuvVyoPK4Jkj5")
h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
BASE = "https://paper-api.alpaca.markets/v2"

LONG = "TQQQ260918C00085000"
SHORT = "TQQQ260918C00100000"
QTY = 10

payload_strategy = {
    "symbol": "TQQQ",
    "qty": QTY,
    "type": "limit",
    "limit_price": 1.90,
    "side": "buy",
    "time_in_force": "day",
    "legs": [
        {"symbol": LONG, "side": "buy", "ratio_qty": 1},
        {"symbol": SHORT, "side": "sell", "ratio_qty": 1},
    ],
}

print("== Intento multi-leg (strategy=debit) ==")
r = requests.post(f"{BASE}/trades?strategy=debit",
                  headers=h, json=payload_strategy, timeout=30)
print(r.status_code)
try:
    j = r.json()
    print(json.dumps(j, indent=1)[:1200])
except Exception:
    print(r.text[:500])

if r.status_code != 200 or ("legs" not in j):
    print("\n== Fallback: pata larga BUY ==")
    order = {
        "symbol": LONG, "qty": QTY, "side": "buy", "type": "limit",
        "limit_price": 2.20, "time_in_force": "day",
    }
    r1 = requests.post(f"{BASE}/orders", headers=h, json=order, timeout=30)
    j1 = r1.json()
    print("BUY LEG:", r1.status_code, j1.get("id"), j1.get("status"),
          j1.get("filled_avg_price"), j1.get("filled_qty"))
    if r1.status_code == 200 and j1.get("status") == "filled":
        print("== Pata corta SELL ==")
        order2 = {
            "symbol": SHORT, "qty": QTY, "side": "sell", "type": "limit",
            "limit_price": 0.44, "time_in_force": "day",
        }
        r2 = requests.post(f"{BASE}/orders", headers=h, json=order2,
                           timeout=30)
        j2 = r2.json()
        print("SELL LEG:", r2.status_code, j2.get("id"), j2.get("status"),
              j2.get("filled_avg_price"), j2.get("filled_qty"))

print("\n== Estado final ==")
r = requests.get(f"{BASE}/positions", headers=h, timeout=30)
for p in r.json():
    print(p["symbol"], p["qty"], p["side"], "avg=%s" % p["avg_entry_price"])
acct = requests.get(f"{BASE}/account", headers=h).json()
print("equity=%.2f cash=%.2f" % (float(acct["equity"]), float(acct["cash"])))
