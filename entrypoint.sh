#!/bin/bash
# Entrypoint de Cloud Run:
# 1. Un servidor HTTP mínimo escucha en $PORT (8080) para el health-check
#    de Cloud Run y para que el dashboard pueda consultar el estado.
# 2. El bot corre en foreground.
set -e

python3 - <<'PY' &
import os, json, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE_FILE = "data/bot_state.json"

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        state = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    state = json.load(f)
            except Exception:
                state = {}
        if self.path == "/diag/state":
            info = {"exists": os.path.exists(STATE_FILE)}
            if info["exists"]:
                info["mtime"] = os.path.getmtime(STATE_FILE)
                info["size"] = os.path.getsize(STATE_FILE)
                try:
                    with open(STATE_FILE) as f:
                        info["sample"] = json.load(f)
                except Exception as e:
                    info["sample"] = f"error: {e}"
            body = json.dumps(info).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/diag/fs":
            out = H._diag_fs()
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if self.path == "/diag/feed":
            out = H._diag_feed()
            body = json.dumps(out).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        body = json.dumps({"status": "ok",
                           "positions": len(state.get("positions", [])),
                           "equity": (state.get("payload") or {}).get("equity")
                                      or state.get("equity")}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    @staticmethod
    def _diag_fs() -> dict:
        """Diagnóstico: prueba credenciales + escritura/lectura en Firestore."""
        try:
            import sys
            sys.path.insert(0, os.environ.get("HOME", "/workspace"))
            from state.firestore_state import write_state_snapshot, _get_db
            write_state_snapshot({"diag": True, "ts": "from-health"})
            db = _get_db()
            docs = list(db.collection("polaris").limit(5).stream())
            return {"ok": True, "docs": [d.id for d in docs]}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    @staticmethod
    def _diag_feed() -> dict:
        """Diagnóstico: intenta obtener barras AAPL 1d desde Alpaca y yfinance."""
        try:
            import sys
            sys.path.insert(0, os.environ.get("HOME", "/workspace"))
            from data.feed import fetch_alpaca, fetch_yfinance
            import datetime
            end = datetime.datetime.now(datetime.timezone.utc)
            start = (end - datetime.timedelta(days=3)).isoformat()
            res = {}
            try:
                df = fetch_alpaca("AAPL", "1d", start, end.isoformat())
                res["alpaca"] = {"ok": True, "rows": len(df)}
            except Exception as e:
                res["alpaca"] = {"ok": False,
                                 "error": f"{type(e).__name__}: {e}"}
            try:
                df2 = fetch_yfinance("AAPL", "1d", start, end.isoformat())
                res["yfinance"] = {"ok": True, "rows": len(df2)}
            except Exception as e:
                res["yfinance"] = {"ok": False,
                                   "error": f"{type(e).__name__}: {e}"}
            return res
        except Exception as e:
            return {"error": f"{type(e).__name__}: {e}"}
    def log_message(self, *a):
        pass

HTTPServer(("0.0.0.0", int(os.environ.get("PORT", 8080))), H).serve_forever()
PY

exec python3 -u bot.py "$@"
