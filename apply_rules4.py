import json, subprocess, urllib.request

tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
proj = "gen-lang-client-0746441136"

content = (
    "rules_version = '2';\n"
    "service cloud.firestore {\n"
    "  match /databases/{database}/documents {\n"
    "    // Bot: Admin SDK omite reglas. Dashboard (api key): solo lectura.\n"
    "    match /{document=**} {\n"
    "      allow read, write: if false;\n"
    "    }\n"
    "    match /polaris/{docId} {\n"
    "      allow read: if true;\n"
    "      allow write: if request.auth != null;\n"
    "    }\n"
    "    match /polaris/{docId}/{subpath=**} {\n"
    "      allow read: if true;\n"
    "      allow write: if request.auth != null;\n"
    "    }\n"
    "    match /backtests/{docId} {\n"
    "      allow read: if true;\n"
    "      allow write: if request.auth != null;\n"
    "    }\n"
    "    match /backtest/{docId} {\n"
    "      allow read: if true;\n"
    "      allow write: if request.auth != null;\n"
    "    }\n"
    "  }\n"
    "}\n"
)

# 1. crear ruleset
upload = {"source": {"files": [{"name": "firestore.rules", "content": content}]}}
req = urllib.request.Request(
    f"https://firebaserules.googleapis.com/v1/projects/{proj}/rulesets",
    data=json.dumps(upload).encode(), method="POST",
    headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
)
with urllib.request.urlopen(req) as r:
    rs = json.load(r)
rs_name = rs["name"]
print("ruleset creado:", rs_name)

# 2. actualizar release: GET release, PATCH con updateMask
rel = "cloud.firestore/polaris"
url = f"https://firebaserules.googleapis.com/v1/projects/{proj}/releases/{rel}"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
with urllib.request.urlopen(req) as r:
    release = json.load(r)
print("release actual:", release["name"], "→", release["rulesetName"])

release["rulesetName"] = rs_name
req = urllib.request.Request(
    url,
    data=json.dumps(release).encode(), method="PATCH",
    headers={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "X-Goog-FieldMask": "rulesetName",
    },
)
try:
    with urllib.request.urlopen(req) as r:
        res = json.load(r)
    print("release actualizada →", res["rulesetName"])
except Exception as e:
    print("patch error:", e)
