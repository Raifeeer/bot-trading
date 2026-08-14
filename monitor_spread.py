"""Monitorea la orden BUY del long (TQQQ 85) hasta el fill y ejecuta el sell
del short (TQQQ 100) como segunda pata. Revisa cada 15 s por hasta 10 min.
"""
import os
import time
import requests

key = os.environ.get("APCA_API_KEY_ID", "PK6NXQZR54PK7DKCFEM7U3ULNE")
secret = os.environ.get("APCA_API_SECRET_KEY",
                        "8HqWabPkVeWgig67o9topXdo6y65scrVuvVyoPK4Jkj5")
h = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
BASE = "https://paper-api.alpaca.markets/v2"
LONG = "TQQQ260918C00085000"
SHORT = "TQQQ260918C00100000"
QTY = 10
ORDER_ID = "e0e82a8b-9412-4c48-8c5f-e955a4482aab"

for i in range(40):
    r = requests.get(f"{BASE}/orders/{ORDER_ID}", headers=h).json()
    st = r["status"]
    r2 = requests.get("https://data.alpaca.markets/v1beta1/options/snapshots",
                      headers=h,
                      params={"symbols": f"{LONG},{SHORT}"},
                      timeout=15).json()
    q = {s: r2["snapshots"][s]["latestQuote"] for s in (LONG, SHORT)}
    print(f"[{i*15//60}:{i*15%60:02d}] bp_long={q[LONG]['bp']:.2f} "
          f"ap_long={q[LONG]['ap']:.2f} bp_short={q[SHORT]['bp']:.2f} "
          f"ap_short={q[SHORT]['ap']:.2f} | BUY order: {st} "
          f"filled={r['filled_qty']}")
    if r["filled_qty"] and int(r["filled_qty"]) >= QTY:
        print("LONG FILL. avg =", r.get("filled_avg_price"))
        order2 = {"symbol": SHORT, "qty": QTY, "side": "sell",
                  "type": "limit", "limit_price": 0.38,
                  "time_in_force": "day"}
        r3 = requests.post(f"{BASE}/orders", headers=h, json=order2,
                           timeout=30)
        j2 = r3.json()
        print("SELL SHORT:", r3.status_code, j2.get("id"), j2.get("status"))
        break
    if st not in ("new", "pending_new", "accepted", "accepted_for_bidding"):
        print("Orden long en estado terminal:", st)
        break
    time.sleep(15)
else:
    print("TIMEOUT 10 min. Estado final:")
    r = requests.get(f"{BASE}/orders/{ORDER_ID}", headers=h).json()
    print(r["status"], r["filled_qty"], r.get("filled_avg_price"))
