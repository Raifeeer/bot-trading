from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "run_polaris_canary_auto_once.py"
spec = importlib.util.spec_from_file_location("polaris_canary_auto_once", MODULE_PATH)
assert spec and spec.loader
canary = importlib.util.module_from_spec(spec)
spec.loader.exec_module(canary)


def test_policy_is_single_small_day_mleg():
    assert canary.MAX_ENTRY_DEBIT == 0.20
    assert canary.MAX_PREMIUM_RISK == 20.0
    assert canary.ENTRY_TIMEOUT == 120
    assert canary.EXIT_TIMEOUT == 120
    assert canary.SYMBOLS == ("AMD", "F", "BB", "NOK", "PLTR", "TQQQ", "TSLA")


def test_select_vertical_uses_valid_quotes_and_calculates_risk(monkeypatch):
    contracts = [
        {
            "symbol": "AMD260918C00100000",
            "type": "call",
            "strike_price": "100",
            "expiration_date": "2026-09-18",
            "tradable": True,
        },
        {
            "symbol": "AMD260918C00101000",
            "type": "call",
            "strike_price": "101",
            "expiration_date": "2026-09-18",
            "tradable": True,
        },
    ]
    quotes = {
        contracts[0]["symbol"]: {"latestQuote": {"bp": 0.09, "ap": 0.10, "bs": 5, "as": 5}},
        contracts[1]["symbol"]: {"latestQuote": {"bp": 0.03, "ap": 0.12, "bs": 5, "as": 5}},
    }

    def fake_api(method, base, path, *, params=None, body=None):
        if path == "/stocks/snapshots":
            return 200, {"AMD": {"latestTrade": {"p": 100}}}
        if path == "/options/contracts":
            return 200, {"option_contracts": contracts}
        if path == "/options/snapshots":
            requested = (params or {}).get("symbols", "").split(",")
            return 200, {"snapshots": {key: quotes[key] for key in requested if key in quotes}}
        raise AssertionError(path)

    monkeypatch.setattr(canary, "api", fake_api)
    pair = canary.select_vertical(dt.datetime(2026, 8, 27, 13, 30, tzinfo=dt.timezone.utc))
    assert pair["underlying"] == "AMD"
    assert pair["long"]["symbol"] == contracts[0]["symbol"]
    assert pair["short"]["symbol"] == contracts[1]["symbol"]
    assert pair["debit"] == 0.07
    assert pair["max_loss_premium_usd"] == 7.0
    assert pair["width_usd"] == 100.0
    assert pair["exit_limit_preview"] == 0.03


def test_select_vertical_rejects_crossed_quotes(monkeypatch):
    contracts = [
        {"symbol": "AMD260918C00100000", "type": "call", "strike_price": "100", "expiration_date": "2026-09-18", "tradable": True},
        {"symbol": "AMD260918C00101000", "type": "call", "strike_price": "101", "expiration_date": "2026-09-18", "tradable": True},
    ]

    def fake_api(method, base, path, *, params=None, body=None):
        if path == "/stocks/snapshots":
            return 200, {"AMD": {"latestTrade": {"p": 100}}}
        if path == "/options/contracts":
            return 200, {"option_contracts": contracts}
        if path == "/options/snapshots":
            return 200, {"snapshots": {
                contracts[0]["symbol"]: {"latestQuote": {"bp": 0.12, "ap": 0.10, "bs": 5, "as": 5}},
                contracts[1]["symbol"]: {"latestQuote": {"bp": 0.03, "ap": 0.14, "bs": 5, "as": 5}},
            }}
        raise AssertionError(path)

    monkeypatch.setattr(canary, "api", fake_api)
    with pytest.raises(RuntimeError, match="no_vertical_with_valid_quote"):
        canary.select_vertical(dt.datetime(2026, 8, 27, 13, 30, tzinfo=dt.timezone.utc))


def test_firestore_encoding_keeps_nested_lifecycle_fields():
    encoded = canary._fs_encode({"status": "entry_submitted", "legs": [{"symbol": "A", "ratio": 1}]})
    assert encoded["mapValue"]["fields"]["status"] == {"stringValue": "entry_submitted"}
    assert encoded["mapValue"]["fields"]["legs"]["arrayValue"]["values"][0]["mapValue"]["fields"]["ratio"] == {"integerValue": "1"}


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def test_verify_cloud_run_uses_regional_v2_endpoint_without_gcloud(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(
            200,
            {
                "traffic": [{"revision": canary.EXPECTED_REVISION, "percent": 100}],
                "template": {"containers": [{"image": "canary-image@sha256:test"}]},
            },
        )

    monkeypatch.setattr(canary, "_gcloud_bin", lambda: None)
    monkeypatch.setattr(canary, "google_access_token", lambda: "adc-token")
    monkeypatch.setattr(canary.requests, "get", fake_get)

    result = canary.verify_cloud_run()

    assert result["revision"] == canary.EXPECTED_REVISION
    assert result["image"] == "canary-image@sha256:test"
    assert calls[0][0] == (
        f"https://run.googleapis.com/v2/projects/{canary.PROJECT}/locations/"
        f"{canary.REGION}/services/{canary.SERVICE}"
    )
    assert calls[0][1]["headers"] == {"Authorization": "Bearer adc-token"}


def test_secret_uses_secret_manager_rest_fallback_without_gcloud(monkeypatch):
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse(200, {"payload": {"data": "cGFwY2Etc2VjcmV0"}})

    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.setattr(canary, "_gcloud_bin", lambda: None)
    monkeypatch.setattr(canary, "google_access_token", lambda: "adc-token")
    monkeypatch.setattr(canary.requests, "get", fake_get)

    assert canary.secret("alpaca-key") == "papca-secret"
    assert calls[0][0].endswith(
        f"/projects/{canary.PROJECT}/secrets/alpaca-key/versions/latest:access"
    )
    assert calls[0][1]["headers"] == {"Authorization": "Bearer adc-token"}


def test_preflight_only_persists_and_never_submits_order(monkeypatch, tmp_path):
    run_id = "canary-test-preflight-only"
    persisted = []
    submitted = []

    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("CANARY_RUN_ID", run_id)
    monkeypatch.setenv("CANARY_PREFLIGHT_ONLY", "1")
    monkeypatch.setattr(canary, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(canary, "fs_get", lambda collection, document_id: (404, {}))
    monkeypatch.setattr(canary, "fs_create", lambda collection, document_id, data: (201, {"updateTime": "t0"}))
    monkeypatch.setattr(
        canary,
        "persist_run",
        lambda current_run_id, data, update_time=None: persisted.append(dict(data)) or "t1",
    )
    monkeypatch.setattr(canary, "verify_cloud_run", lambda: {"revision": canary.EXPECTED_REVISION})
    monkeypatch.setattr(canary, "verify_recent_cloud_run_health", lambda: {"bad_markers": 0})
    monkeypatch.setattr(canary, "verify_paper_account", lambda: {"equity": "100000"})
    monkeypatch.setattr(canary, "market_open", lambda: {"is_open": True})
    monkeypatch.setattr(
        canary,
        "select_vertical",
        lambda as_of: {
            "underlying": "AMD",
            "expiration": "2026-09-18",
            "type": "call",
            "spot": 100.0,
            "long": {"symbol": "AMD260918C00100000", "ask": 0.10, "bid": 0.09},
            "short": {"symbol": "AMD260918C00101000", "bid": 0.03, "ask": 0.04},
            "debit": 0.07,
            "max_loss_premium_usd": 7.0,
            "max_profit_premium_usd": 93.0,
            "exit_limit_preview": 0.03,
            "width_usd": 100.0,
        },
    )
    monkeypatch.setattr(canary, "find_existing_order", lambda client_id: submitted.append(("lookup", client_id)))
    monkeypatch.setattr(canary, "submit_mleg", lambda *args, **kwargs: submitted.append(("submit", args, kwargs)))

    assert canary.main() == 0
    assert submitted == []
    assert persisted[-1]["status"] == "preflight_only"
    assert persisted[-1]["orders_allowed"] is False


def test_recent_health_allows_handled_sip_fallback_with_fresh_telemetry(monkeypatch):
    entries = [
        {"textPayload": "feed WARNING AMD: subscription does not permit querying recent SIP data"},
        {"textPayload": "feed WARNING AMD: reintento con yfinance"},
        {"textPayload": "bot INFO Tick OK — equity=96914.08 posiciones=0"},
        {"textPayload": "state.firestore INFO Estado escrito en Firestore: polaris/2026-08-27"},
    ]

    monkeypatch.setattr(canary, "_gcloud_bin", lambda: None)
    monkeypatch.setattr(canary, "google_access_token", lambda: "adc-token")
    monkeypatch.setattr(
        canary.requests,
        "post",
        lambda *args, **kwargs: _FakeResponse(200, {"entries": entries}),
    )

    result = canary.verify_recent_cloud_run_health()

    assert result["bad_markers"] == 0
    assert result["tick_ok_count"] == 1
    assert result["firestore_write_count"] == 1
    assert result["handled_feed_fallback_count"] == 2


def test_recent_health_fails_without_fresh_tick_or_firestore(monkeypatch):
    monkeypatch.setattr(canary, "_gcloud_bin", lambda: None)
    monkeypatch.setattr(canary, "google_access_token", lambda: "adc-token")
    monkeypatch.setattr(
        canary.requests,
        "post",
        lambda *args, **kwargs: _FakeResponse(
            200,
            {"entries": [{"textPayload": "feed WARNING AMD: reintento con yfinance"}]},
        ),
    )

    with pytest.raises(RuntimeError, match="missing_recent_tick_ok"):
        canary.verify_recent_cloud_run_health()


def test_recent_health_still_fails_on_critical_traceback(monkeypatch):
    monkeypatch.setattr(canary, "_gcloud_bin", lambda: None)
    monkeypatch.setattr(canary, "google_access_token", lambda: "adc-token")
    monkeypatch.setattr(
        canary.requests,
        "post",
        lambda *args, **kwargs: _FakeResponse(
            200,
            {
                "entries": [
                    {"textPayload": "bot INFO Tick OK"},
                    {"textPayload": "state.firestore INFO Estado escrito en Firestore"},
                    {"textPayload": "Traceback (most recent call last):"},
                ]
            },
        ),
    )

    with pytest.raises(RuntimeError, match="critical_error_in_recent_logs"):
        canary.verify_recent_cloud_run_health()


def test_failure_path_persists_orders_disabled(monkeypatch, tmp_path):
    persisted = []

    monkeypatch.setenv("APCA_API_KEY_ID", "paper-key")
    monkeypatch.setenv("APCA_API_SECRET_KEY", "paper-secret")
    monkeypatch.setenv("CANARY_RUN_ID", "canary-test-failure-closed")
    monkeypatch.delenv("CANARY_PREFLIGHT_ONLY", raising=False)
    monkeypatch.setattr(canary, "RUN_ROOT", tmp_path)
    monkeypatch.setattr(canary, "fs_get", lambda collection, document_id: (404, {}))
    monkeypatch.setattr(canary, "fs_create", lambda collection, document_id, data: (201, {"updateTime": "t0"}))
    monkeypatch.setattr(
        canary,
        "persist_run",
        lambda current_run_id, data, update_time=None: persisted.append(dict(data)) or "t1",
    )
    monkeypatch.setattr(canary, "verify_cloud_run", lambda: {"revision": canary.EXPECTED_REVISION})
    monkeypatch.setattr(canary, "verify_recent_cloud_run_health", lambda: {"bad_markers": 0})
    monkeypatch.setattr(canary, "verify_paper_account", lambda: {"equity": "100000"})
    monkeypatch.setattr(canary, "market_open", lambda: {"is_open": True})
    monkeypatch.setattr(canary, "select_vertical", lambda as_of: (_ for _ in ()).throw(RuntimeError("quote_failure")))

    with pytest.raises(RuntimeError, match="quote_failure"):
        canary.main()

    assert persisted[-1]["status"] == "failed_needs_review"
    assert persisted[-1]["orders_allowed"] is False
