import json, subprocess, urllib.request

tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
proj = "gen-lang-client-0746441136"
db = "polaris"
for path in ["backtests/latest", "backtest/latest"]:
    url = f"https://firestore.googleapis.com/v1/projects/{proj}/databases/{db}/documents/polaris/{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
    try:
        with urllib.request.urlopen(req) as r:
            d = json.load(r)
        fs = d.get("fields", {})
        print("DOC OK:", path)
        for k, v in fs.items():
            if "mapValue" in v:
                print("  ", k, ": map with keys", list(v["mapValue"]["fields"].keys())[:12])
            elif "arrayValue" in v:
                vals = v["arrayValue"]["values"]
                print("  ", k, f": array({len(vals)}) first:", json.dumps(vals[0])[:150] if vals else "(empty)")
            else:
                print("  ", k, ":", v)
    except Exception as e:
        print(path, "error:", e)
