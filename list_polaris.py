import json, subprocess, urllib.request

tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
proj = "gen-lang-client-0746441136"
db = "polaris"
url = f"https://firestore.googleapis.com/v1/projects/{proj}/databases/{db}/documents:runQuery"
payload = json.dumps({"structuredQuery": {"from": [{"collectionId": "polaris"}], "limit": 20}}).encode()
req = urllib.request.Request(url, data=payload, method="POST",
                             headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req) as r:
        body = r.read().decode()
    if len(body) > 500:
        open("/tmp/runquery_raw.txt", "w").write(body)
        print("raw saved to /tmp/runquery_raw.txt (len", len(body), ")")
    lines = []
    for l in body.strip().splitlines():
        l = l.strip()
        if l:
            try:
                lines.append(json.loads(l))
            except json.JSONDecodeError:
                print("skip line:", l[:120])
    for l in lines:
        if "document" in l:
            d = l["document"]
            print("DOC:", d["name"].split(f"/databases/{db}/documents/")[1], "| updated:", d.get("updateTime", "")[:19])
            if "fields" in d:
                fs = d["fields"]
                if "payload" in fs:
                    p = fs["payload"].get("mapValue", {}).get("fields", {})
                    print("  keys(payload):", sorted(p.keys()))
                    for k in ("equity", "cash", "trading_mode"):
                        if k in p:
                            v = p[k]
                            print(f"  {k} =", v.get("numberValue") or v.get("stringValue"))
except Exception as e:
    print("error:", e)
