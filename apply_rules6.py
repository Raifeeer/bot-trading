import json, subprocess, urllib.request

tok = subprocess.run(["gcloud", "auth", "print-access-token"], capture_output=True, text=True).stdout.strip()
proj = "gen-lang-client-0746441136"
rs = "projects/gen-lang-client-0746441136/rulesets/a8050a88-3fc6-40d3-aca1-6dc2140fc52c"

rel = "cloud.firestore/polaris"
url = f"https://firebaserules.googleapis.com/v1/projects/{proj}/releases/{rel}"
body = {
    "name": url.replace("https://firebaserules.googleapis.com/v1/", "projects/"),
    "rulesetName": rs,
}
req = urllib.request.Request(
    url,
    data=json.dumps(body).encode(), method="PATCH",
    headers={
        "Authorization": f"Bearer {tok}",
        "Content-Type": "application/json",
        "X-Goog-UpdateMask": "rulesetName",
    },
)
try:
    with urllib.request.urlopen(req) as r:
        res = json.load(r)
    print("release actualizada →", res["rulesetName"])
except Exception as e:
    print("patch error:", e)
