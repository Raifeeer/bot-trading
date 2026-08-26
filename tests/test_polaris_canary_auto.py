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
