#!/usr/bin/env python3
"""Canary PAPER única y fail-closed para validar el ciclo de salida.

No reactiva los motores del bot. Solo acepta el contrato y precio fijados en la
confirmación del usuario. Si el mercado no está abierto, el preflight falla y
no se envía nada. Si una orden no llena dentro del timeout, se cancela sin
perseguir precio. Si una salida queda ambigua, se marca needs_review y no se
reintenta.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import time
from pathlib import Path

import requests

PROJECT = "gen-lang-client-0746441136"
GCLOUD = "/home/ubuntu/tools/google-cloud-sdk/bin/gcloud"
TRADING_BASE = "https://paper-api.alpaca.markets/v2"
DATA_BASE = "https://data.alpaca.markets/v1beta1"
FIRESTORE_BASE = (
    f"https://firestore.googleapis.com/v1/projects/{PROJECT}"
    "/databases/polaris/documents"
)
CONTRACT = "F260828C00015000"
UNDERLYING = "F"
QTY = 1
ENTRY_LIMIT = 0.02
POLL_SECONDS = 5
TIMEOUT_SECONDS = 120
RUN_ID = "canary-20260825-f260828c00015000"
CANARY_COLLECTION = "polaris_canary_runs"
EXIT_COLLECTION = "polaris_exit_ledger"
RUN_PATH = Path("/home/ubuntu/backtests") / f"{RUN_ID}.json"


def secret(name: str) -> str:
    return subprocess.check_output([
        GCLOUD, "secrets", "versions", "access", "latest",
        f"--secret={name}", f"--project={PROJECT}"], text=True).strip()

KEY = secret("alpaca-key")
SECRET = secret("alpaca-secret")
HEADERS = {
    "APCA-API-KEY-ID": KEY,
    "APCA-API-SECRET-KEY": SECRET,
    "Content-Type": "application/json",
}


def api(method: str, url: str, *, params=None, body=None):
    response = requests.request(
        method, url, headers=HEADERS, params=params, json=body, timeout=25
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    return response.status_code, payload


def fs_token() -> str:
    return subprocess.check_output([
        GCLOUD, "auth", "print-access-token"], text=True).strip()


def fs_encode(value):
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if value is None:
        return {"nullValue": None}
    if isinstance(value, list):
        return {"arrayValue": {"values": [fs_encode(v) for v in value]}}
    return {"stringValue": str(value)}


def fs_fields(data: dict) -> dict:
    return {key: fs_encode(value) for key, value in data.items()}


def firestore_request(method: str, path: str, *, params=None, body=None):
    headers = {"Authorization": f"Bearer {fs_token()}", "Content-Type": "application/json"}
    response = requests.request(
        method, f"{FIRESTORE_BASE}/{path}", headers=headers,
        params=params, json=body, timeout=25
    )
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:500]}
    return response.status_code, payload


def fs_create(collection: str, document_id: str, data: dict):
    return firestore_request(
        "POST", collection, params={"documentId": document_id},
        body={"fields": fs_fields(data)},
    )


def fs_get(collection: str, document_id: str):
    return firestore_request("GET", f"{collection}/{document_id}")


def fs_patch(collection: str, document_id: str, data: dict, update_time: str | None = None):
    body = {"fields": fs_fields(data)}
    if update_time:
        body["currentDocument"] = {"updateTime": update_time}
    return firestore_request("PATCH", f"{collection}/{document_id}", body=body)


def write_run(data: dict, update_time: str | None = None):
    data = dict(data)
    data["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    RUN_PATH.parent.mkdir(parents=True, exist_ok=True)
    RUN_PATH.write_text(json.dumps({k: v for k, v in data.items() if k not in {"api_key", "api_secret"}}, indent=2))
    return fs_patch(CANARY_COLLECTION, RUN_ID, data, update_time=update_time)


def persist_run(data: dict, update_time: str | None = None) -> str | None:
    code, payload = write_run(data, update_time)
    if code not in (200, 201):
        raise RuntimeError(f"canary_run_update_failed_http_{code}")
    return payload.get("updateTime")


def order_status(order_id: str):
    code, payload = api("GET", f"{TRADING_BASE}/orders/{order_id}")
    if code != 200:
        raise RuntimeError(f"order_status_http_{code}")
    return payload


def wait_for_terminal(order_id: str, timeout: int = TIMEOUT_SECONDS):
    deadline = time.time() + timeout
    while time.time() < deadline:
        order = order_status(order_id)
        status = str(order.get("status", "")).lower()
        if status in {"filled", "canceled", "cancelled", "rejected", "expired"}:
            return order
        time.sleep(POLL_SECONDS)
    return order_status(order_id)


def cancel_order(order_id: str):
    code, payload = api("DELETE", f"{TRADING_BASE}/orders/{order_id}")
    if code not in (200, 204, 404):
        raise RuntimeError(f"cancel_http_{code}:{payload}")


def entry_quote_allowed(ask: float, max_debit: float = ENTRY_LIMIT) -> bool:
    try:
        return 0 < float(ask) <= float(max_debit)
    except (TypeError, ValueError):
        return False


def exit_quote_allowed(bid: float, ask: float) -> bool:
    try:
        return 0 < float(bid) <= float(ask)
    except (TypeError, ValueError):
        return False


def verify_cloud_run_contained():
    output = subprocess.check_output([
        GCLOUD, "run", "services", "describe", "polaris-bot",
        "--project=gen-lang-client-0746441136", "--region=us-central1",
        "--format=value(status.traffic)",
    ], text=True, timeout=30).strip()
    if "polaris-bot-cbdc186" not in output or "'percent': 100" not in output:
        raise RuntimeError("cloud_run_revision_not_contained")
    return output


def verify_empty_account():
    code, account = api("GET", f"{TRADING_BASE}/account")
    if code != 200 or account.get("status") != "ACTIVE":
        raise RuntimeError("account_not_active")
    code, positions = api("GET", f"{TRADING_BASE}/positions")
    if code != 200 or positions:
        raise RuntimeError("positions_not_empty")
    code, orders = api("GET", f"{TRADING_BASE}/orders", params={"status": "open", "limit": 100})
    if code != 200 or orders:
        raise RuntimeError("open_orders_not_empty")
    return account


def get_snapshot():
    code, payload = api(
        "GET", f"{DATA_BASE}/options/snapshots",
        params={"symbols": CONTRACT},
    )
    if code != 200:
        raise RuntimeError(f"snapshot_http_{code}")
    return (payload.get("snapshots") or {}).get(CONTRACT) or {}


def ledger_id():
    return "exit-" + hashlib.sha256(f"{CONTRACT}|{RUN_ID}".encode()).hexdigest()[:40]


def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    run = {
        "run_id": RUN_ID,
        "status": "preflight",
        "mode": "PAPER",
        "contract": CONTRACT,
        "underlying": UNDERLYING,
        "qty": QTY,
        "entry_limit": ENTRY_LIMIT,
        "max_debit": QTY * ENTRY_LIMIT * 100,
        "started_at": now,
    }
    code, run_doc = fs_create(CANARY_COLLECTION, RUN_ID, run)
    if code not in (200, 201):
        raise RuntimeError(f"canary_run_claim_failed_http_{code}")
    run_update_time = run_doc.get("updateTime")

    run["cloud_run_traffic"] = verify_cloud_run_contained()
    code, clock = api("GET", f"{TRADING_BASE}/clock")
    if code != 200 or not clock.get("is_open"):
        run["status"] = "aborted_market_closed"
        run_update_time = persist_run(run, run_update_time)
        print(json.dumps({"status": run["status"], "next_open": clock.get("next_open")}))
        return 0

    account = verify_empty_account()
    contract_code, contract = api("GET", f"{TRADING_BASE}/options/contracts/{CONTRACT}")
    if contract_code != 200 or contract.get("tradable") is False:
        raise RuntimeError("contract_not_tradable")
    snapshot = get_snapshot()
    quote = snapshot.get("latestQuote") or {}
    ask = float(quote.get("ap") or 0)
    bid = float(quote.get("bp") or 0)
    if not entry_quote_allowed(ask):
        raise RuntimeError(f"entry_ask_above_limit:{ask}")

    run.update({
        "status": "entry_submitting",
        "account_equity": str(account.get("equity")),
        "entry_bid": bid,
        "entry_ask": ask,
        "preflight_clock": clock.get("timestamp"),
    })
    run_update_time = persist_run(run, run_update_time)

    client_order_id = f"polaris-{RUN_ID}"
    code, entry = api("POST", f"{TRADING_BASE}/orders", body={
        "symbol": CONTRACT,
        "qty": str(QTY),
        "side": "buy",
        "type": "limit",
        "limit_price": f"{ENTRY_LIMIT:.2f}",
        "time_in_force": "day",
        "client_order_id": client_order_id,
    })
    if code not in (200, 201):
        run.update({"status": "entry_rejected", "entry_http": code})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError(f"entry_rejected_http_{code}")
    entry_id = str(entry.get("id"))
    run.update({"entry_order_id": entry_id, "status": "entry_submitted"})
    run_update_time = persist_run(run, run_update_time)

    entry_final = wait_for_terminal(entry_id)
    entry_status = str(entry_final.get("status", "")).lower()
    if entry_status != "filled":
        if entry_status not in {"canceled", "cancelled", "rejected", "expired"}:
            cancel_order(entry_id)
            entry_final = wait_for_terminal(entry_id, timeout=30)
        run.update({
            "status": "entry_not_filled",
            "entry_final_status": entry_final.get("status"),
            "entry_filled_qty": entry_final.get("filled_qty"),
        })
        run_update_time = persist_run(run, run_update_time)
        print(json.dumps({"status": run["status"], "entry_order_id": entry_id}))
        return 0

    filled_qty = float(entry_final.get("filled_qty") or 0)
    if filled_qty != QTY:
        run.update({"status": "entry_partial_needs_review", "entry_final": entry_final})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError("entry_partial_needs_review")

    intent = {
        "status": "submitting",
        "active": True,
        "position_key": CONTRACT,
        "position": {"symbol": CONTRACT, "qty": QTY, "entry_order_id": entry_id},
        "entry_order_id": entry_id,
        "entry_filled_qty": filled_qty,
        "entry_filled_avg_price": entry_final.get("filled_avg_price"),
        "entry_ts": entry_final.get("filled_at") or now,
        "reason": "authorized_canary_exit",
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "version": 1,
    }
    exit_id = ledger_id()
    code, ledger_doc = fs_create(EXIT_COLLECTION, exit_id, intent)
    if code not in (200, 201):
        run.update({"status": "exit_ledger_claim_failed_needs_review", "ledger_id": exit_id})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError("exit_ledger_claim_failed_needs_review")

    snapshot = get_snapshot()
    quote = snapshot.get("latestQuote") or {}
    bid = float(quote.get("bp") or 0)
    ask = float(quote.get("ap") or 0)
    if not exit_quote_allowed(bid, ask):
        update = {**intent, "status": "needs_review", "active": True, "version": 2}
        fs_patch(EXIT_COLLECTION, exit_id, update, ledger_doc.get("updateTime"))
        run.update({"status": "exit_quote_unsafe_needs_review", "ledger_id": exit_id})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError("exit_quote_unsafe_needs_review")

    run.update({"status": "exit_submitting", "ledger_id": exit_id, "exit_bid": bid, "exit_ask": ask})
    run_update_time = persist_run(run, run_update_time)
    result = fs_patch(EXIT_COLLECTION, exit_id, {
        "status": "submitted", "active": True, "version": 2,
        "exit_limit": bid, "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }, ledger_doc.get("updateTime"))
    if result[0] not in (200, 201):
        run.update({"status": "exit_ledger_update_failed_needs_review"})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError("exit_ledger_update_failed_needs_review")

    code, exit_order = api("POST", f"{TRADING_BASE}/orders", body={
        "symbol": CONTRACT,
        "qty": str(QTY),
        "side": "sell",
        "type": "limit",
        "limit_price": f"{bid:.2f}",
        "time_in_force": "day",
        "client_order_id": f"polaris-{RUN_ID}-exit",
    })
    if code not in (200, 201):
        fs_patch(EXIT_COLLECTION, exit_id, {
            "status": "needs_review", "active": True, "version": 3,
            "failure": f"exit_submit_http_{code}",
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }, result[1].get("updateTime"))
        run.update({"status": "exit_rejected_needs_review", "exit_http": code})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError(f"exit_rejected_needs_review_http_{code}")
    exit_order_id = str(exit_order.get("id"))
    run.update({"exit_order_id": exit_order_id, "status": "exit_submitted"})
    run_update_time = persist_run(run, run_update_time)
    exit_final = wait_for_terminal(exit_order_id)
    exit_status = str(exit_final.get("status", "")).lower()
    if exit_status != "filled":
        if exit_status not in {"canceled", "cancelled", "rejected", "expired"}:
            cancel_order(exit_order_id)
            exit_final = wait_for_terminal(exit_order_id, timeout=30)
        fs_patch(EXIT_COLLECTION, exit_id, {
            "status": "needs_review", "active": True, "version": 3,
            "exit_order_id": exit_order_id,
            "exit_status": exit_final.get("status"),
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }, result[1].get("updateTime"))
        run.update({"status": "exit_not_filled_needs_review", "exit_final": exit_final})
        run_update_time = persist_run(run, run_update_time)
        print(json.dumps({"status": run["status"], "exit_order_id": exit_order_id}))
        return 0

    code, positions = api("GET", f"{TRADING_BASE}/positions")
    if code != 200 or any(str(p.get("symbol")) == CONTRACT for p in positions):
        run.update({"status": "exit_filled_position_remains_needs_review", "exit_final": exit_final})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError("exit_filled_position_remains_needs_review")

    result = fs_patch(EXIT_COLLECTION, exit_id, {
        "status": "completed", "active": False, "version": 3,
        "exit_order_id": exit_order_id,
        "exit_filled_qty": exit_final.get("filled_qty"),
        "exit_filled_avg_price": exit_final.get("filled_avg_price"),
        "completion_reason": "broker_position_absent",
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }, result[1].get("updateTime"))
    if result[0] not in (200, 201):
        run.update({"status": "completed_broker_ledger_needs_review", "exit_order_id": exit_order_id})
        run_update_time = persist_run(run, run_update_time)
        raise RuntimeError("completed_broker_ledger_needs_review")
    run.update({"status": "completed", "exit_final": exit_final})
    persist_run(run, run_update_time)
    print(json.dumps({"status": run["status"], "entry_order_id": entry_id, "exit_order_id": exit_order_id}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
