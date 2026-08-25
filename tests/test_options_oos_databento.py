from __future__ import annotations

import pandas as pd
import pytest

from research.options_oos_databento import (
    DatabentoConfig,
    DatabentoUnavailable,
    fetch_opra_range,
    normalize_definitions,
    normalize_quotes,
    validate_oos_quotes,
)


def _definitions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAPL 260101C00200000"],
            "expiration": ["2026-01-01"],
            "strike": [200.0],
            "option_type": ["call"],
        }
    )


def _valid_quotes() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": ["AAPL 260101C00200000", "AAPL 260101C00200000"],
            "timestamp": ["2026-08-01T13:30:00Z", "2026-08-01T13:31:00Z"],
            "bid": [1.00, 1.05],
            "ask": [1.10, 1.15],
            "bid_size": [10, 12],
            "ask_size": [11, 13],
        }
    )


def test_missing_key_aborts_before_sdk_or_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    config = DatabentoConfig(start="2026-08-01", end="2026-08-02", symbols=("AAPL",))
    with pytest.raises(DatabentoUnavailable, match="DATABENTO_API_KEY"):
        fetch_opra_range(config)


def test_normalize_cbbo_columns_and_gate_pass() -> None:
    raw = pd.DataFrame(
        {
            "raw_symbol": ["AAPL 260101C00200000", "AAPL 260101C00200000"],
            "ts_event": ["2026-08-01T13:30:00Z", "2026-08-01T13:31:00Z"],
            "bid_px_00": [1.00, 1.05],
            "ask_px_00": [1.10, 1.15],
            "bid_sz_00": [10, 12],
            "ask_sz_00": [11, 13],
        }
    )
    normalized = normalize_quotes(raw)
    result = validate_oos_quotes(normalized, _definitions(), require_sizes=True)
    assert result.passed is True
    assert result.invalid_quote_rows == 0
    assert result.duplicate_rows == 0


def test_normalize_definition_aliases() -> None:
    raw = pd.DataFrame(
        {
            "raw_symbol": ["AAPL 260101C00200000"],
            "expiry": ["2026-01-01"],
            "strike_price": [200.0],
            "instrument_class": ["call"],
        }
    )
    normalized = normalize_definitions(raw)
    assert set(("symbol", "expiration", "strike", "option_type")) <= set(normalized.columns)
    assert normalized.loc[0, "strike"] == 200.0


def test_missing_definitions_fails_closed() -> None:
    result = validate_oos_quotes(_valid_quotes(), None, require_sizes=True)
    assert result.passed is False
    assert "point_in_time_definitions_missing" in result.violations


def test_crossed_quote_fails_closed() -> None:
    quotes = _valid_quotes()
    quotes.loc[0, "ask"] = 0.90
    result = validate_oos_quotes(quotes, _definitions(), require_sizes=True)
    assert result.passed is False
    assert "invalid_or_crossed_quotes" in result.violations


def test_duplicate_timestamp_fails_closed() -> None:
    quotes = _valid_quotes()
    quotes.loc[1, "timestamp"] = quotes.loc[0, "timestamp"]
    result = validate_oos_quotes(quotes, _definitions(), require_sizes=True)
    assert result.passed is False
    assert "duplicate_symbol_timestamps" in result.violations


def test_missing_quote_size_can_be_required() -> None:
    quotes = _valid_quotes().drop(columns=["bid_size", "ask_size"])
    result = validate_oos_quotes(quotes, _definitions(), require_sizes=True)
    assert result.passed is False
    assert set(result.missing_columns) == {"ask_size", "bid_size"}
