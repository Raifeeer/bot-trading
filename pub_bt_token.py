"""Publica backtests/latest usando el access token de gcloud (sin ADC)."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publish_backtest import build_doc

TOK = subprocess.check_output(
    ["/home/ubuntu/google-cloud-sdk/bin/gcloud", "auth", "print-access-token"],
    text=True).strip()
print(f"token length: {len(TOK)}")

from google.auth.credentials import Credentials
from google.cloud import firestore


class TokCreds(Credentials):
    def __init__(self, token):
        super().__init__()
        self.token = token

    def refresh(self, request):
        pass


doc = build_doc()
if not doc["scenarios"]:
    print("Sin escenarios", file=sys.stderr)
    sys.exit(1)

db = firestore.Client(
    project="gen-lang-client-0746441136",
    database=os.environ.get("FIRESTORE_DATABASE", "polaris"),
    credentials=TokCreds(TOK),
)
db.collection("backtests").document("latest").set(doc)
print(f"OK: {len(doc['scenarios'])} escenarios | best={doc['best']['scenario']} "
      f"({doc['best']['retorno_pct']}%)")
