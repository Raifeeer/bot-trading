import json, subprocess, urllib.request

tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
proj = "gen-lang-client-0746441136"

rules = {
    "name": f"projects/{proj}/databases/(default)/securityRules",
    "source": {
        "files": [
            {
                "name": "security.rules",
                "content": (
                    "rules_version = '2';\n"
                    "service cloud.firestore {\n"
                    "  match /databases/{database}/documents {\n"
                    "    match /polaris/{doc} {\n"
                    "      allow read: if true;\n"
                    "      allow write: if request.auth != null || true;\n"
                    "    }\n"
                    "    match /backtests/{doc} {\n"
                    "      allow read: if true;\n"
                    "      allow write: if request.auth != null || true;\n"
                    "    }\n"
                    "    match /backtest/{doc} {\n"
                    "      allow read: if true;\n"
                    "      allow write: if request.auth != null || true;\n"
                    "    }\n"
                    "  }\n"
                    "}\n"
                ),
            }
        ]
    },
}

# Check current rules
url = f"https://firebaserules.googleapis.com/v1/projects/{proj}/releases"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
try:
    with urllib.request.urlopen(req) as r:
        rels = json.load(r)
    print("releases:", json.dumps(rels)[:500])
except Exception as e:
    print("list error:", e)

# Update default db rules
url = f"https://firebaserules.googleapis.com/v1/projects/{proj}:testRules"
# Simpler: upload ruleset then update release
upload = {
    "source": {"files": rules["source"]["files"]}
}
req = urllib.request.Request(
    f"https://firebaserules.googleapis.com/v1/projects/{proj}/rulesets",
    data=json.dumps(upload).encode(), method="POST",
    headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as r:
        rs = json.load(r)
    print("ruleset:", rs["name"])
except Exception as e:
    print("upload error:", e); exit(1)
