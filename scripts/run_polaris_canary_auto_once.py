#!/usr/bin/env python3
"""Canary PAPER autónoma de una vertical MLeg, una sola vez.

La política queda fijada en código: Alpaca PAPER, una vertical MLeg de un
contrato, débito máximo de 0,20 USD por acción (20 USD de riesgo de prima),
solo DAY, cancelación si no llena en 120 s y cierre con bid/ask válido. No hay
fallback a patas individuales ni reintento de una ejecución ambigua.

Este script es research/operaciones controladas; no modifica Cloud Run ni
habilita el loop principal de Polaris.
"""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import requests

PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "gen-lang-client-0746441136")
REGION = os.environ.get("CLOUD_RUN_REGION", "us-central1")
SERVICE = os.environ.get("POLARIS_SERVICE", "polaris-bot")
EXPECTED_REVISION = os.environ.get("POLARIS_EXPECTED_REVISION", "polaris-bot-telegramrotate2")
TRADING_BASE = "https://paper-api.alpaca.markets/v2"
DATA_BASE = "https://data.alpaca.markets/v2"
OPTIONS_DATA_BASE = "https://data.alpaca.markets/v1beta1"
FIRESTORE_BASE = f"https://firestore.googleapis.com/v1/projects/{PROJECT}/databases/polaris/documents"
GCLOUD = "/home/ubuntu/tools/google-cloud-sdk/bin/gcloud"
SYMBOLS = ("AMD", "F", "BB", "NOK", "PLTR", "TQQQ", "TSLA")
MAX_ENTRY_DEBIT = 0.20
MAX_PREMIUM_RISK = 20.00
COMMISSION_PER_CONTRACT_SIDE = 0.65
ENTRY_TIMEOUT = 120
EXIT_TIMEOUT = 120
POLL_SECONDS = 5
RUN_ROOT = Path(os.environ.get("CANARY_RUN_ROOT", "/tmp/polaris-canary"))
logger = logging.getLogger("polaris.canary.auto")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _json_response(response: requests.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:300]}


def api_headers() -> dict[str, str]:
    key = os.environ.get("APCA_API_KEY_ID", "")
    secret = os.environ.get("APCA_API_SECRET_KEY", "")
    if not key or not secret:
        raise RuntimeError("missing_alpaca_credentials")
    return {
        "APCA-API-KEY-ID": key,
        "APCA-API-SECRET-KEY": secret,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def api(method: str, base: str, path: str, *, params: dict | None = None, body: dict | None = None):
    response = requests.request(
        method,
        base + path,
        headers=api_headers(),
        params=params,
        json=body,
        timeout=25,
    )
    return response.status_code, _json_response(response)


def _gcloud_bin() -> str | None:
    return os.environ.get("GCLOUD_BIN") or shutil.which("gcloud")


def google_access_token() -> str:
    explicit = os.environ.get("GOOGLE_OAUTH_ACCESS_TOKEN")
    if explicit:
        return explicit
    gcloud = _gcloud_bin()
    if gcloud:
        try:
            return subprocess.check_output(
                [gcloud, "auth", "print-access-token"], text=True, timeout=30
            ).strip()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        import google.auth
        from google.auth.transport.requests import Request

        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        if not credentials.valid or credentials.expired:
            credentials.refresh(Request())
        if not credentials.token:
            raise RuntimeError("google_adc_token_missing")
        return credentials.token
    except Exception as exc:
        raise RuntimeError("google_adc_unavailable") from exc


def secret(name: str) -> str:
    env_name = {
        "alpaca-key": "APCA_API_KEY_ID",
        "alpaca-secret": "APCA_API_SECRET_KEY",
    }.get(name)
    if env_name and os.environ.get(env_name):
        return os.environ[env_name]
    gcloud = _gcloud_bin()
    if gcloud:
        return subprocess.check_output(
            [gcloud, "secrets", "versions", "access", "latest", f"--secret={name}", f"--project={PROJECT}"],
            text=True,
            timeout=30,
        ).strip()
    response = requests.get(
        f"https://secretmanager.googleapis.com/v1/projects/{PROJECT}/secrets/{name}/versions/latest:access",
        headers={"Authorization": f"Bearer {google_access_token()}"},
        timeout=30,
    )
    if response.status_code != 200:
        raise RuntimeError(f"secret_access_failed_http_{response.status_code}")
    payload = _json_response(response).get("payload", {}).get("data")
    if not payload:
        raise RuntimeError(f"secret_payload_missing:{name}")
    return base64.b64decode(payload).decode("utf-8").strip()


def firestore_token() -> str:
    return google_access_token()


def _fs_encode(value: Any) -> dict:
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if value is None:
        return {"nullValue": None}
    if isinstance(value, list):
        return {"arrayValue": {"values": [_fs_encode(item) for item in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {key: _fs_encode(item) for key, item in value.items()}}}
    return {"stringValue": str(value)}


def _fs_fields(data: dict) -> dict:
    return {key: _fs_encode(value) for key, value in data.items()}


def firestore_request(method: str, path: str, *, params=None, body=None):
    response = requests.request(
        method,
        f"{FIRESTORE_BASE}/{path}",
        headers={"Authorization": f"Bearer {firestore_token()}", "Content-Type": "application/json"},
        params=params,
        json=body,
        timeout=25,
    )
    return response.status_code, _json_response(response)


def fs_get(collection: str, document_id: str):
    return firestore_request("GET", f"{collection}/{document_id}")


def fs_create(collection: str, document_id: str, data: dict):
    return firestore_request(
        "POST",
        collection,
        params={"documentId": document_id},
        body={"fields": _fs_fields(data)},
    )


def fs_patch(collection: str, document_id: str, data: dict, update_time: str | None = None):
    params = [("updateMask.fieldPaths", key) for key in data]
    if update_time:
        params.append(("currentDocument.updateTime", update_time))
    return firestore_request(
        "PATCH",
        f"{collection}/{document_id}",
        params=params,
        body={"fields": _fs_fields(data)},
    )


def run_file(run_id: str) -> Path:
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    return RUN_ROOT / f"{run_id}.json"


def persist_run(run_id: str, data: dict, update_time: str | None = None):
    payload = dict(data)
    payload["updated_at"] = _now().isoformat()
    run_file(run_id).write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    code, response = fs_patch("polaris_canary_runs", run_id, payload, update_time)
    if code not in (200, 201):
        raise RuntimeError(f"canary_run_update_failed_http_{code}")
    return response.get("updateTime")


def verify_cloud_run() -> dict:
    gcloud = _gcloud_bin()
    if gcloud:
        raw = subprocess.check_output(
            [
                gcloud,
                "run",
                "services",
                "describe",
                SERVICE,
                f"--project={PROJECT}",
                f"--region={REGION}",
                "--format=json",
            ],
            text=True,
            timeout=30,
        )
        service = json.loads(raw)
    else:
        response = requests.get(
            f"https://run.googleapis.com/v2/projects/{PROJECT}/locations/{REGION}/services/{SERVICE}",
            headers={"Authorization": f"Bearer {google_access_token()}"},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(f"cloud_run_lookup_failed_http_{response.status_code}")
        service = _json_response(response)
    traffic = service.get("status", {}).get("traffic", [])
    if not traffic:
        traffic = service.get("traffic", [])
    active = [item for item in traffic if int(item.get("percent", 0)) == 100]
    active_revision = active[0].get("revisionName") if active else None
    if active_revision is None and active:
        active_revision = active[0].get("revision")
    if len(active) != 1 or active_revision != EXPECTED_REVISION:
        raise RuntimeError("cloud_run_revision_not_expected_or_not_100_percent")
    containers = service.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
    if not containers:
        containers = service.get("template", {}).get("containers", [])
    if not containers:
        raise RuntimeError("cloud_run_container_missing")
    return {"revision": EXPECTED_REVISION, "image": containers[0].get("image", "")}


def verify_recent_cloud_run_health() -> dict:
    start = (_now() - dt.timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
    filter_text = (
        f'resource.type=cloud_run_revision AND '
        f'resource.labels.service_name={SERVICE} AND '
        f'resource.labels.revision_name={EXPECTED_REVISION} AND '
        f'timestamp>="{start}"'
    )
    gcloud = _gcloud_bin()
    if gcloud:
        raw = subprocess.check_output(
            [
                gcloud,
                "logging",
                "read",
                filter_text,
                f"--project={PROJECT}",
                "--limit=250",
                "--format=value(textPayload,jsonPayload.message)",
            ],
            text=True,
            timeout=45,
        )
        lines = raw.splitlines()
    else:
        response = requests.post(
            "https://logging.googleapis.com/v2/entries:list",
            headers={"Authorization": f"Bearer {google_access_token()}"},
            json={
                "resourceNames": [f"projects/{PROJECT}"],
                "filter": filter_text,
                "orderBy": "timestamp desc",
                "pageSize": 250,
            },
            timeout=45,
        )
        if response.status_code != 200:
            raise RuntimeError(f"cloud_run_log_lookup_failed_http_{response.status_code}")
        entries = _json_response(response).get("entries", [])
        lines = []
        for entry in entries:
            payload = entry.get("textPayload")
            if payload:
                lines.append(str(payload))
            payload = entry.get("jsonPayload")
            if isinstance(payload, dict):
                lines.append(json.dumps(payload, sort_keys=True))
    bad_markers = ("Traceback", "CRITICAL", " ERROR ", "409 Conflict", "SIP", "^VIX")
    warnings = [line.strip()[:300] for line in lines if any(marker in line for marker in bad_markers)]
    if warnings:
        raise RuntimeError("cloud_run_or_feed_warning_in_recent_logs")
    return {"window_minutes": 10, "bad_markers": 0}


def verify_paper_account() -> dict:
    code, account = api("GET", TRADING_BASE, "/account")
    if code != 200 or account.get("status") != "ACTIVE":
        raise RuntimeError("account_not_active")
    base = str(account.get("account_number", ""))
    # PAPER is enforced by the endpoint and by the expected Cloud Run revision.
    code, positions = api("GET", TRADING_BASE, "/positions")
    if code != 200 or not isinstance(positions, list) or positions:
        raise RuntimeError("positions_not_empty")
    code, orders = api("GET", TRADING_BASE, "/orders", params={"status": "open", "limit": 100, "nested": "true"})
    if code != 200 or not isinstance(orders, list) or orders:
        raise RuntimeError("open_orders_not_empty")
    return {"account_number_present": bool(base), "equity": account.get("equity"), "cash": account.get("cash")}


def market_open() -> dict:
    code, clock = api("GET", TRADING_BASE, "/clock")
    if code != 200:
        raise RuntimeError(f"clock_http_{code}")
    if not clock.get("is_open"):
        raise RuntimeError("market_closed")
    return clock


def _number(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _latest_stock_price(symbol: str) -> float:
    code, payload = api("GET", DATA_BASE, "/stocks/snapshots", params={"symbols": symbol})
    if code != 200:
        return 0.0
    item = (payload.get(symbol) or {}) if isinstance(payload, dict) else {}
    trade = item.get("latestTrade") or {}
    quote = item.get("latestQuote") or {}
    return _number(trade.get("p")) or ((_number(quote.get("bp")) + _number(quote.get("ap"))) / 2)


def _snapshot_map(symbols: list[str]) -> dict:
    if not symbols:
        return {}
    code, payload = api("GET", OPTIONS_DATA_BASE, "/options/snapshots", params={"symbols": ",".join(symbols)})
    if code != 200 or not isinstance(payload, dict):
        return {}
    return payload.get("snapshots") or {}


def select_vertical(as_of: dt.datetime) -> dict:
    lo = (as_of.date() + dt.timedelta(days=14)).isoformat()
    hi = (as_of.date() + dt.timedelta(days=60)).isoformat()
    candidates: list[dict] = []
    for underlying in SYMBOLS:
        spot = _latest_stock_price(underlying)
        if spot <= 0:
            continue
        code, payload = api(
            "GET",
            TRADING_BASE,
            "/options/contracts",
            params={
                "underlying_symbols": underlying,
                "status": "active",
                "expiration_date_gte": lo,
                "expiration_date_lte": hi,
                "type": "call",
                "limit": 200,
            },
        )
        if code != 200:
            continue
        contracts = payload.get("option_contracts", []) if isinstance(payload, dict) else []
        # Keep the nearest calls around spot and limit the quote request.
        contracts = [
            c for c in contracts
            if c.get("symbol") and c.get("tradable") is not False and _number(c.get("strike_price")) >= spot
        ]
        contracts.sort(key=lambda c: (abs(_number(c.get("strike_price")) - spot), c.get("expiration_date", "")))
        contracts = contracts[:60]
        snap_map = _snapshot_map([c["symbol"] for c in contracts])
        for contract in contracts:
            quote = (snap_map.get(contract["symbol"]) or {}).get("latestQuote") or {}
            bid = _number(quote.get("bp"))
            ask = _number(quote.get("ap"))
            bid_size = _number(quote.get("bs"))
            ask_size = _number(quote.get("as"))
            if bid <= 0 or ask <= 0 or ask < bid or bid_size < 1 or ask_size < 1:
                continue
            if ask - bid > 0.10 or ask > MAX_ENTRY_DEBIT:
                continue
            candidates.append({
                "underlying": underlying,
                "spot": spot,
                "symbol": contract["symbol"],
                "type": contract.get("type", "call"),
                "strike": _number(contract.get("strike_price")),
                "expiration": contract.get("expiration_date"),
                "bid": bid,
                "ask": ask,
                "bid_size": bid_size,
                "ask_size": ask_size,
                "spread": ask - bid,
            })
    pairs = []
    for long in candidates:
        for short in candidates:
            if (long["underlying"], long["expiration"], long["type"]) != (short["underlying"], short["expiration"], short["type"]):
                continue
            if long["strike"] >= short["strike"] or long["symbol"] == short["symbol"]:
                continue
            debit = long["ask"] - short["bid"]
            width = (short["strike"] - long["strike"]) * 100
            if debit <= 0 or debit > MAX_ENTRY_DEBIT or debit * 100 > MAX_PREMIUM_RISK or width <= 0:
                continue
            exit_limit_preview = short["ask"] - long["bid"]
            if exit_limit_preview <= 0:
                continue
            pairs.append({
                "underlying": long["underlying"],
                "spot": long["spot"],
                "expiration": long["expiration"],
                "type": long["type"],
                "long": long,
                "short": short,
                "debit": round(debit, 2),
                "width_usd": round(width, 2),
                "max_loss_premium_usd": round(debit * 100, 2),
                "max_profit_premium_usd": round(max(width - debit * 100, 0), 2),
                "exit_limit_preview": round(exit_limit_preview, 2),
                "quote_quality": round(long["spread"] + short["spread"], 6),
            })
    if not pairs:
        raise RuntimeError("no_vertical_with_valid_quote_under_policy")
    # Prefer the tightest two-leg quote, then lowest premium risk, then nearest strike.
    pairs.sort(key=lambda pair: (pair["quote_quality"], pair["debit"], abs(pair["long"]["strike"] - pair["spot"])))
    return pairs[0]


def find_existing_order(client_order_id: str) -> dict | None:
    code, orders = api("GET", TRADING_BASE, "/orders", params={"status": "all", "limit": 100, "nested": "true", "direction": "desc"})
    if code != 200 or not isinstance(orders, list):
        raise RuntimeError("order_history_lookup_failed")
    for order in orders:
        if order.get("client_order_id") == client_order_id:
            return order
    return None


def wait_terminal(order_id: str, timeout: int) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        code, order = api("GET", TRADING_BASE, f"/orders/{order_id}")
        if code != 200:
            raise RuntimeError(f"order_status_http_{code}")
        last = order
        status = str(order.get("status", "")).lower()
        if status in {"filled", "canceled", "cancelled", "rejected", "expired"}:
            return order
        time.sleep(POLL_SECONDS)
    code, last = api("GET", TRADING_BASE, f"/orders/{order_id}")
    if code != 200:
        raise RuntimeError(f"order_status_timeout_lookup_http_{code}")
    return last


def cancel_order(order_id: str):
    code, payload = api("DELETE", TRADING_BASE, f"/orders/{order_id}")
    if code not in (200, 204, 404):
        raise RuntimeError(f"cancel_failed_http_{code}:{payload}")


def _order_record(order: dict) -> dict:
    return {
        "id": str(order.get("id", "")),
        "status": order.get("status"),
        "filled_qty": order.get("filled_qty"),
        "filled_avg_price": order.get("filled_avg_price"),
        "client_order_id": order.get("client_order_id"),
        "legs": [
            {
                "symbol": leg.get("symbol"),
                "side": leg.get("side"),
                "ratio_qty": leg.get("ratio_qty"),
                "status": leg.get("status"),
                "filled_qty": leg.get("filled_qty"),
            }
            for leg in (order.get("legs") or [])
        ],
    }


def submit_mleg(legs: list[dict], limit_price: float, client_order_id: str, closing: bool) -> dict:
    from execution.alpaca_executor import AlpacaExecutor

    executor = AlpacaExecutor(dry_run=False)
    executor.connect()
    record = executor.submit_spread(
        legs,
        time_in_force="day",
        order_type="limit",
        limit_price=limit_price,
        client_order_id=client_order_id,
        closing=closing,
    )
    if not record.get("id"):
        raise RuntimeError("mleg_submit_without_order_id")
    return record


def verify_flat(symbols: list[str]) -> bool:
    code, positions = api("GET", TRADING_BASE, "/positions")
    if code != 200 or not isinstance(positions, list):
        raise RuntimeError("post_canary_position_lookup_failed")
    held = {str(position.get("symbol")) for position in positions}
    if held.intersection(symbols):
        return False
    code, orders = api("GET", TRADING_BASE, "/orders", params={"status": "open", "limit": 100, "nested": "true"})
    if code != 200 or not isinstance(orders, list):
        raise RuntimeError("post_canary_order_lookup_failed")
    return not orders


def main() -> int:
    if os.environ.get("BOT_DRY_RUN") == "1":
        raise RuntimeError("dry_run_environment_not_allowed_for_paper_canary")
    os.environ.setdefault("APCA_API_KEY_ID", secret("alpaca-key"))
    os.environ.setdefault("APCA_API_SECRET_KEY", secret("alpaca-secret"))
    as_of = _now()
    run_id = os.environ.get("CANARY_RUN_ID", f"canary-auto-{as_of.date().isoformat()}")
    existing_code, _existing = fs_get("polaris_canary_runs", run_id)
    if existing_code == 200:
        raise RuntimeError("canary_run_already_exists_no_retry")
    if existing_code != 404:
        raise RuntimeError(f"canary_run_claim_lookup_failed_http_{existing_code}")
    run = {
        "run_id": run_id,
        "status": "preflight",
        "mode": "PAPER",
        "policy": "one vertical MLeg, qty 1, debit <= 0.20, max premium risk <= 20, DAY, 120s entry/exit timeout",
        "started_at": as_of.isoformat(),
        "orders_allowed": True,
        "production_config_changed": False,
    }
    code, created = fs_create("polaris_canary_runs", run_id, run)
    if code not in (200, 201):
        raise RuntimeError(f"canary_run_claim_failed_http_{code}")
    update_time = created.get("updateTime")
    try:
        run["cloud_run"] = verify_cloud_run()
        run["cloud_run_health"] = verify_recent_cloud_run_health()
        run["account"] = verify_paper_account()
        try:
            run["clock"] = market_open()
        except RuntimeError as exc:
            if str(exc) != "market_closed":
                raise
            run.update({"status": "aborted_market_closed", "orders_allowed": False})
            persist_run(run_id, run, update_time)
            return 0
        pair = select_vertical(as_of)
        run["selection"] = {
            "underlying": pair["underlying"],
            "expiration": pair["expiration"],
            "type": pair["type"],
            "spot": pair["spot"],
            "long": pair["long"],
            "short": pair["short"],
            "debit": pair["debit"],
            "max_loss_premium_usd": pair["max_loss_premium_usd"],
            "max_profit_premium_usd": pair["max_profit_premium_usd"],
            "exit_limit_preview": pair["exit_limit_preview"],
            "width_usd": pair["width_usd"],
        }
        if pair["debit"] <= 0 or pair["debit"] > MAX_ENTRY_DEBIT or pair["max_loss_premium_usd"] > MAX_PREMIUM_RISK:
            raise RuntimeError("selected_vertical_outside_policy")
        fingerprint = hashlib.sha256(f"{run_id}|{pair['long']['symbol']}|{pair['short']['symbol']}".encode()).hexdigest()[:24]
        client_id = f"polaris-auto-{as_of.date().strftime('%Y%m%d')}-{fingerprint}"
        run.update({"status": "entry_preflight_passed", "client_order_id": client_id, "entry_limit": pair["debit"]})
        update_time = persist_run(run_id, run, update_time)
        if os.environ.get("CANARY_PREFLIGHT_ONLY") == "1":
            run.update({"status": "preflight_only", "orders_allowed": False})
            persist_run(run_id, run, update_time)
            return 0
        existing_order = find_existing_order(client_id)
        if existing_order is not None:
            raise RuntimeError("client_order_id_already_present_no_retry")
        entry = submit_mleg(
            [
                {"symbol": pair["long"]["symbol"], "side": "buy", "qty": 1, "position_intent": "buy_to_open", "limit_price": pair["long"]["ask"]},
                {"symbol": pair["short"]["symbol"], "side": "sell", "qty": 1, "position_intent": "sell_to_open", "limit_price": pair["short"]["bid"]},
            ],
            pair["debit"],
            client_id,
            closing=False,
        )
        run.update({"status": "entry_submitted", "entry_order": entry})
        update_time = persist_run(run_id, run, update_time)
        final_entry = wait_terminal(entry["id"], ENTRY_TIMEOUT)
        run["entry_final"] = _order_record(final_entry)
        if str(final_entry.get("status", "")).lower() != "filled":
            if str(final_entry.get("status", "")).lower() not in {"canceled", "cancelled", "rejected", "expired"}:
                cancel_order(entry["id"])
                final_entry = wait_terminal(entry["id"], 30)
            run.update({"status": "entry_not_filled", "entry_final": _order_record(final_entry)})
            persist_run(run_id, run, update_time)
            return 0
        if _number(final_entry.get("filled_qty")) != 1:
            run["status"] = "entry_partial_needs_review"
            persist_run(run_id, run, update_time)
            return 2

        close_quotes = _snapshot_map([pair["long"]["symbol"], pair["short"]["symbol"]])
        long_q = (close_quotes.get(pair["long"]["symbol"]) or {}).get("latestQuote") or {}
        short_q = (close_quotes.get(pair["short"]["symbol"]) or {}).get("latestQuote") or {}
        long_bid = _number(long_q.get("bp"))
        short_ask = _number(short_q.get("ap"))
        if long_bid <= 0 or short_ask <= 0 or short_ask < long_bid:
            run["status"] = "exit_quote_invalid_needs_review"
            persist_run(run_id, run, update_time)
            return 2
        exit_limit = round(short_ask - long_bid, 2)
        exit_client_id = f"{client_id}-exit"
        run.update({"status": "exit_preflight_passed", "exit_limit": exit_limit, "exit_bid_long": long_bid, "exit_ask_short": short_ask})
        update_time = persist_run(run_id, run, update_time)
        exit_order = submit_mleg(
            [
                {"symbol": pair["long"]["symbol"], "side": "sell", "qty": 1, "position_intent": "sell_to_close", "limit_price": long_bid},
                {"symbol": pair["short"]["symbol"], "side": "buy", "qty": 1, "position_intent": "buy_to_close", "limit_price": short_ask},
            ],
            exit_limit,
            exit_client_id,
            closing=True,
        )
        run.update({"status": "exit_submitted", "exit_order": exit_order})
        update_time = persist_run(run_id, run, update_time)
        final_exit = wait_terminal(exit_order["id"], EXIT_TIMEOUT)
        run["exit_final"] = _order_record(final_exit)
        if str(final_exit.get("status", "")).lower() != "filled":
            if str(final_exit.get("status", "")).lower() not in {"canceled", "cancelled", "rejected", "expired"}:
                cancel_order(exit_order["id"])
                final_exit = wait_terminal(exit_order["id"], 30)
            run.update({"status": "exit_not_filled_needs_review", "exit_final": _order_record(final_exit)})
            persist_run(run_id, run, update_time)
            return 2
        if not verify_flat([pair["long"]["symbol"], pair["short"]["symbol"]]):
            run["status"] = "exit_filled_position_remains_needs_review"
            persist_run(run_id, run, update_time)
            return 2
        run.update({
            "status": "completed",
            "active": False,
            "entry_commission_estimate": 2 * COMMISSION_PER_CONTRACT_SIDE,
            "exit_commission_estimate": 2 * COMMISSION_PER_CONTRACT_SIDE,
            "completed_at": _now().isoformat(),
        })
        persist_run(run_id, run, update_time)
        return 0
    except Exception as exc:
        run.update({"status": "failed_needs_review", "error_type": type(exc).__name__, "error": str(exc)[:300]})
        try:
            persist_run(run_id, run, update_time)
        except (RuntimeError, OSError, subprocess.SubprocessError, requests.RequestException) as persist_exc:
            logger.error("canary state persistence failed after %s: %s", type(exc).__name__, persist_exc)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
