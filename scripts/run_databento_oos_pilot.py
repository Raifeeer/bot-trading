#!/usr/bin/env python3
"""Read-only Databento OPRA pilot for Polaris OOS research.

This script never imports the trading bot or submits broker orders. Network
access requires both --execute and DATABENTO_API_KEY. Without them it exits
cleanly with a blocked plan.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from research.options_oos_databento import (
    DatabentoConfig,
    DatabentoUnavailable,
    fetch_opra_range,
    normalize_definitions,
    normalize_quotes,
    validate_oos_quotes,
    write_manifest,
)

DEFAULT_SYMBOLS = ("AMD", "F", "BB", "NOK", "PLTR", "TQQQ", "TSLA")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, help="UTC ISO-8601 start")
    parser.add_argument("--end", required=True, help="UTC ISO-8601 end")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--out", default="/home/ubuntu/backtests/databento_opra_pilot")
    parser.add_argument("--schema", default="cbbo-1m", choices=("cbbo-1m", "cbbo-1s", "cmbp-1", "trades"))
    parser.add_argument("--execute", action="store_true", help="Allow the read-only data request")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())
    config = DatabentoConfig(
        dataset="OPRA.PILLAR",
        schema=args.schema,
        stype_in="parent",
        start=args.start,
        end=args.end,
        symbols=symbols,
    )
    api_key = os.environ.get("DATABENTO_API_KEY")
    if not args.execute or not api_key:
        print(json.dumps({
            "status": "blocked_no_network",
            "reason": "--execute y DATABENTO_API_KEY son obligatorios; no se ha realizado consulta.",
            "dataset": config.dataset,
            "schema": config.schema,
            "start": config.start,
            "end": config.end,
            "symbols": list(config.symbols),
            "orders_allowed": False,
        }, sort_keys=True))
        return 0

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        raw_quotes = fetch_opra_range(config, api_key=api_key)
        quotes = normalize_quotes(raw_quotes)
        raw_definitions = fetch_opra_range(
            DatabentoConfig(
                dataset=config.dataset,
                schema="definition",
                stype_in=config.stype_in,
                start=config.start,
                end=config.end,
                symbols=config.symbols,
            ),
            api_key=api_key,
        )
        definitions = normalize_definitions(raw_definitions)
    except (DatabentoUnavailable, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "blocked_data_request", "reason": str(exc), "orders_allowed": False}, sort_keys=True))
        return 2

    quotes_path = output.with_name(output.name + "_quotes.csv")
    definitions_path = output.with_name(output.name + "_definitions.csv")
    manifest_path = output.with_name(output.name + "_manifest.json")
    quotes.to_csv(quotes_path, index=False)
    definitions.to_csv(definitions_path, index=False)
    gate = validate_oos_quotes(quotes, definitions, require_sizes=False, require_intraday=True)
    write_manifest(manifest_path, config=config, files=(quotes_path, definitions_path), gate=gate)
    result = {
        "status": "passed" if gate.passed else "rejected_data_gate",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest": str(manifest_path),
        "quotes_rows": len(quotes),
        "definitions_rows": len(definitions),
        "data_gate": gate.as_dict(),
        "orders_allowed": False,
    }
    print(json.dumps(result, sort_keys=True))
    return 0 if gate.passed else 3


if __name__ == "__main__":
    sys.exit(main())
