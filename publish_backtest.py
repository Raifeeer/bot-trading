"""Publica los resultados consolidados de los backtests (S1-S71) al
documento backtests/latest en Firestore (DB 'polaris').

Así el dashboard lee métricas de backtest REALES (cero mock).

Uso: GCLOUD_ACCESS_TOKEN=$(gcloud auth print-access-token) FIRESTORE_DATABASE=polaris python3 publish_backtest.py
Requiere GOOGLE_APPLICATION_CREDENTIALS o gcloud auth (en Cloud Run usa la
identidad del servicio; localmente activa la cuenta con `gcloud auth login`).
"""
import csv
import os
import sys
from datetime import datetime, timezone

TOP = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TOP)


def load_summaries():
    path = os.path.join(TOP, "backtests", "bt_resumen.csv")
    if not os.path.exists(path):
        path = "/home/ubuntu/backtests/bt_resumen.csv"
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def build_doc():
    rows = load_summaries()
    key = lambda r: float(r.get("retorno_pct", 0) or 0)
    rows_sorted = sorted(rows, key=key, reverse=True)
    top = [
        {
            "id": r["scenario"],
            "name": r.get("name", ""),
            "motor": r.get("motor", ""),
            "window_days": r.get("window_days", ""),
            "retorno_pct": float(r.get("retorno_pct", 0) or 0),
            "trades": int(float(r.get("trades", 0) or 0)),
            "win_rate_pct": float(r.get("win_rate", 0) or 0),
            "max_drawdown_pct": float(r.get("max_drawdown_pct", 0) or 0),
            "pnl_total": float(r.get("pnl_total", 0) or 0),
        }
        for r in rows_sorted[:30]
    ]
    best = rows_sorted[0] if rows_sorted else None
    return {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "loop_backtests.py (71 escenarios S1-S71)",
        "capital_inicial": 100.0,
        "scenarios": top,
        "best": {
            "scenario": best["scenario"],
            "name": best.get("name", ""),
            "retorno_pct": float(best.get("retorno_pct", 0) or 0),
            "trades": int(float(best.get("trades", 0) or 0)),
            "win_rate_pct": float(best.get("win_rate", 0) or 0),
        } if best else None,
    }


def main():
    doc = build_doc()
    if not doc["scenarios"]:
        print("Sin filas en backtests/resumen.csv", file=sys.stderr)
        sys.exit(1)
    doc["source"] = "loop_backtests.py (89 escenarios S1-S89)"
    try:
        from google.cloud import firestore
        import google.oauth2.credentials as _creds
        database = os.environ.get("FIRESTORE_DATABASE", "polaris")
        creds = None
        token = os.environ.get("GCLOUD_ACCESS_TOKEN", "").strip()
        if token:
            import google.oauth2.credentials as _creds
            creds = _creds.Credentials(token=token)
        if creds is None:
            try:
                import google.auth  # noqa: E402
                creds, _ = google.auth.default(
                    scopes=["https://www.googleapis.com/auth/datastore"])
            except Exception:
                creds = None
        project = os.environ.get(
            "GOOGLE_CLOUD_PROJECT",
            "gen-lang-client-0746441136")
        db = firestore.Client(project=project, database=database,
                              credentials=creds)
        # Colección 'backtests' (histórico) + 'polaris/backtest' (doc legible
        # públicamente por el dashboard; las reglas de la release 'polaris' solo
        # exponen lectura en polaris/*).
        db.collection("backtests").document("latest").set(doc)
        db.collection("polaris").document("backtest").set(doc)
        print(f"Publicado backtests/latest y polaris/backtest: "
              f"{len(doc['scenarios'])} escenarios, "
              f"best={doc['best']['scenario']} ({doc['best']['retorno_pct']}%)")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
