import json, subprocess, urllib.request

tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
proj = "gen-lang-client-0746441136"
db = "polaris"
url = f"https://firestore.googleapis.com/v1/projects/{proj}/databases/{db}/documents/polaris/backtests/latest"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
with urllib.request.urlopen(req) as r:
    d = json.load(r)
fs = d.get("fields", {})
print("keys:", sorted(fs.keys()))
for k, v in fs.items():
    if "arrayValue" in v:
        vals = v["arrayValue"]["values"]
        print(k, f": array len={len(vals)}")
        if vals:
            print("  first:", json.dumps(vals[0])[:400])
    elif "mapValue" in v:
        print(k, ": map keys:", list(v["mapValue"]["fields"].keys()))
    elif "integerValue" in v or "doubleValue" in v:
        print(k, ":", v.get("integerValue", v.get("doubleValue")))
    else:
        print(k, ":", v)
