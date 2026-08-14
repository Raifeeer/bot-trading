import json, subprocess, urllib.request

tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
proj = "gen-lang-client-0746441136"
rs = "projects/gen-lang-client-0746441136/rulesets/59b1a702-123a-4a8b-8e22-4367754b27cd"

# list current releases
url = f"https://firebaserules.googleapis.com/v1/projects/{proj}/releases"
req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}"})
with urllib.request.urlopen(req) as r:
    rels = json.load(r)["releases"]
for rel in rels:
    print("release:", rel["name"], "→", rel["rulesetName"])

# update main release
url = f"https://firebaserules.googleapis.com/v1/projects/{proj}/releases/cloud.firestore"
req = urllib.request.Request(
    url,
    data=json.dumps({"name": url.split("projects/")[1], "rulesetName": rs}).encode(),
    method="PATCH",
    headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"},
)
try:
    with urllib.request.urlopen(req) as r:
        res = json.load(r)
    print("updated release:", res["name"], "→", res["rulesetName"])
except Exception as e:
    print("update error:", e)
