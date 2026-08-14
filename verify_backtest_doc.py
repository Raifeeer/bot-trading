"""Verifica lectura pública del doc polaris/backtest (API key del cliente)."""
import json
import urllib.request

KEY = "AIzaSyBivr7jzNMg6F4uE0zR65eeKOMmRemmiq4"
url = ("https://firestore.googleapis.com/v1/projects/"
       "gen-lang-client-0746441136/databases/polaris/documents/"
       "polaris/backtest?key=" + KEY)
with urllib.request.urlopen(url) as r:
    d = json.load(r)
f = d.get("fields", {})
sc = f.get("scenarios", {}).get("arrayValue", {}).get("values", [])
best = f.get("best", {}).get("mapValue", {}).get("fields", {})
print("updated_at:", f.get("updated_at", {}).get("stringValue"))
print("best:", best.get("scenario", {}).get("stringValue"),
      best.get("retorno_pct", {}).get("doubleValue"), "%")
print("n escenarios:", len(sc))
print("top3:", [(s.get("mapValue", {}).get("fields", {}).get("id", {}).get("stringValue"),
                s.get("mapValue", {}).get("fields", {}).get("retorno_pct", {}).get("doubleValue"))
               for s in sc[:3]])
