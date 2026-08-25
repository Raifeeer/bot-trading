"""Safe, read-only Databento OPRA adapter and OOS data gate.

This module deliberately has no side effects at import time and never submits
orders. Databento is optional: the production bot does not import this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import importlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping

import pandas as pd


class DatabentoUnavailable(RuntimeError):
    """Raised when the optional SDK or API key is not available."""


@dataclass(frozen=True)
class DatabentoConfig:
    dataset: str = "OPRA.PILLAR"
    schema: str = "cbbo-1m"
    stype_in: str = "parent"
    start: str = ""
    end: str = ""
    symbols: tuple[str, ...] = ()


@dataclass(frozen=True)
class GateResult:
    passed: bool
    rows: int
    missing_columns: tuple[str, ...]
    violations: tuple[str, ...]
    duplicate_rows: int
    invalid_quote_rows: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "rows": self.rows,
            "missing_columns": list(self.missing_columns),
            "violations": list(self.violations),
            "duplicate_rows": self.duplicate_rows,
            "invalid_quote_rows": self.invalid_quote_rows,
        }


QUOTE_ALIASES = {
    "ts_event": "timestamp",
    "ts_recv": "timestamp",
    "bid_px_00": "bid",
    "ask_px_00": "ask",
    "bid_sz_00": "bid_size",
    "ask_sz_00": "ask_size",
    "raw_symbol": "symbol",
    "instrument_id": "instrument_id",
}

DEFINITION_ALIASES = {
    "raw_symbol": "symbol",
    "expiration": "expiration",
    "expiration_date": "expiration",
    "expiry": "expiration",
    "strike_price": "strike",
    "strike_px": "strike",
    "strike": "strike",
    "option_type": "option_type",
    "instrument_class": "option_type",
}


def _load_databento() -> Any:
    try:
        return importlib.import_module("databento")
    except ImportError as exc:
        raise DatabentoUnavailable(
            "Databento SDK no está instalado; instala la dependencia solo en el entorno de investigación."
        ) from exc


def fetch_opra_range(config: DatabentoConfig, api_key: str | None = None) -> Any:
    """Fetch read-only OPRA data; raises before network access without a key."""
    if not api_key:
        raise DatabentoUnavailable("DATABENTO_API_KEY no está configurada; no se realiza ninguna consulta.")
    if not config.start or not config.end or not config.symbols:
        raise ValueError("start, end y symbols son obligatorios para una consulta reproducible.")
    databento = _load_databento()
    client = databento.Historical(api_key)
    return client.timeseries.get_range(
        dataset=config.dataset,
        schema=config.schema,
        symbols=list(config.symbols),
        stype_in=config.stype_in,
        start=config.start,
        end=config.end,
    )


def _to_frame(records: Any) -> pd.DataFrame:
    if isinstance(records, pd.DataFrame):
        return records.copy()
    if hasattr(records, "to_df"):
        return records.to_df().reset_index()
    if isinstance(records, Mapping):
        return pd.DataFrame(records)
    return pd.DataFrame(list(records))


def normalize_quotes(records: Any) -> pd.DataFrame:
    """Normalize Databento DBN/DataFrame output to a stable quote schema."""
    frame = _to_frame(records)
    frame.columns = [str(column).lower() for column in frame.columns]
    rename = {old: new for old, new in QUOTE_ALIASES.items() if old in frame.columns}
    frame = frame.rename(columns=rename)
    if "timestamp" not in frame.columns and frame.index.name in {"ts_event", "ts_recv"}:
        frame = frame.reset_index().rename(columns={frame.index.name: "timestamp"})
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("bid", "ask", "bid_size", "ask_size", "strike"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values([column for column in ("symbol", "timestamp") if column in frame.columns]).reset_index(drop=True)


def normalize_definitions(records: Any) -> pd.DataFrame:
    """Normalize Databento instrument-definition output."""
    frame = _to_frame(records)
    frame.columns = [str(column).lower() for column in frame.columns]
    rename = {old: new for old, new in DEFINITION_ALIASES.items() if old in frame.columns}
    frame = frame.rename(columns=rename)
    for column in ("expiration", "strike"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce") if column == "strike" else frame[column].astype(str)
    return frame


def validate_oos_quotes(
    quotes: pd.DataFrame,
    definitions: pd.DataFrame | None = None,
    *,
    require_sizes: bool = False,
    require_intraday: bool = True,
) -> GateResult:
    """Reject incomplete or execution-unrealistic quote datasets."""
    required = {"timestamp", "symbol", "bid", "ask"}
    if require_sizes:
        required |= {"bid_size", "ask_size"}
    missing = tuple(sorted(required - set(quotes.columns)))
    definition_missing: tuple[str, ...] = ()
    if definitions is None:
        definition_missing = ("definitions_frame",)
    else:
        definition_required = {"symbol", "expiration", "strike", "option_type"}
        definition_missing = tuple(sorted(definition_required - set(definitions.columns)))
    violations: list[str] = []
    invalid_rows = 0
    duplicate_rows = 0
    if missing:
        violations.append("missing_required_columns")
    else:
        timestamp = pd.to_datetime(quotes["timestamp"], utc=True, errors="coerce")
        numeric = quotes[["bid", "ask"]].apply(pd.to_numeric, errors="coerce")
        invalid = timestamp.isna() | numeric.isna().any(axis=1) | (numeric["bid"] <= 0) | (numeric["ask"] < numeric["bid"])
        invalid_rows = int(invalid.sum())
        if invalid_rows:
            violations.append("invalid_or_crossed_quotes")
        keys = [column for column in ("symbol", "timestamp") if column in quotes.columns]
        if len(keys) == 2:
            duplicate_rows = int(quotes.duplicated(keys).sum())
            if duplicate_rows:
                violations.append("duplicate_symbol_timestamps")
        if require_intraday:
            if timestamp.dropna().dt.normalize().nunique() == 0:
                violations.append("no_timestamped_intraday_data")
            elif timestamp.dropna().dt.floor("min").nunique() <= 1:
                violations.append("insufficient_intraday_granularity")
    if definitions is None or definition_missing:
        violations.append("point_in_time_definitions_missing")
    passed = not violations
    return GateResult(passed, len(quotes), missing, tuple(sorted(set(violations))), duplicate_rows, invalid_rows)


def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(path: str | Path, *, config: DatabentoConfig, files: Iterable[str | Path], gate: GateResult) -> None:
    payload = {
        "provider": "Databento",
        "dataset": config.dataset,
        "schema": config.schema,
        "stype_in": config.stype_in,
        "start": config.start,
        "end": config.end,
        "symbols": list(config.symbols),
        "files": [{"path": str(file), "sha256": sha256_file(file)} for file in files],
        "data_gate": gate.as_dict(),
        "orders_allowed": False,
        "production_config_changed": False,
    }
    Path(path).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
