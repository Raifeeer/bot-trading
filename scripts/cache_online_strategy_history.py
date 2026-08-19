"""Cache read-only para estrategias online seleccionadas.

Extiende el universo histórico de opciones existente para BWB y mide gates de
0DTE/1DTE. Las barras disponibles son diarias; el manifiesto no permite tratar
ese material como backtest intradía válido.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", "/home/ubuntu/backtests/setup_history"))
SOURCE_CONTRACTS = Path(os.environ.get("WHEEL_CONTRACTS", "/home/ubuntu/backtests/wheel_option_history_2026-08-18/contracts.json"))
OUT_DIR = Path(os.environ.get("ONLINE_OPTION_HISTORY_DIR", "/home/ubuntu/backtests/online_option_history_2026-08-19"))
SYMBOLS = ["AMD", "BB", "F", "NOK", "PLTR", "TQQQ", "TSLA"]
START = pd.Timestamp("2026-04-01", tz="UTC")
END = pd.Timestamp("2026-08-07", tz="UTC")
DTE_TARGETS = [14, 30, 45]
WIDTHS = [0.05, 0.10]


def _spot(symbol: str, day: pd.Timestamp) -> float | None:
    path = HISTORY_DIR / f"{symbol}.pkl"
    if not path.exists():
        return None
    frame = pd.read_pickle(path)
    rows = frame[frame.index.normalize() == day.normalize()]
    return float(rows["close"].iloc[-1]) if len(rows) else None


def _fridays() -> list[pd.Timestamp]:
    return [day for day in pd.date_range(START, END, freq="D") if day.weekday() == 4]


def _all_days() -> list[pd.Timestamp]:
    return list(pd.date_range(START, END, freq="D"))


def _expiry_candidates(contracts: list[dict], day: pd.Timestamp, target: int, low: int, high: int) -> list[str]:
    expiries = []
    for item in contracts:
        expiry = pd.Timestamp(item["expiration"], tz="UTC")
        dte = (expiry - day).days
        if low <= dte <= high:
            expiries.append(item["expiration"])
    unique = sorted(set(expiries), key=lambda value: abs((pd.Timestamp(value, tz="UTC") - day).days - target))
    return unique


def _select(contracts: list[dict], expiry: str, kind: str, spot: float, moneyness: float) -> dict | None:
    target = spot * (1.0 + moneyness)
    pool = [item for item in contracts if item["expiration"] == expiry and item["type"] == kind]
    return min(pool, key=lambda item: abs(float(item["strike"]) - target)) if pool else None


def _leg(item: dict, symbol: str, quantity: int, decision: pd.Timestamp, structure: str, dte: int, width: float) -> dict:
    return {"symbol": item["symbol"], "underlying": symbol, "type": item["type"], "strike": float(item["strike"]), "expiration": item["expiration"], "quantity": quantity, "decision": decision.date().isoformat(), "dte_target": dte, "width": width, "structure": structure}


def _bwb(contracts: list[dict], symbol: str, day: pd.Timestamp, kind: str, dte: int, width: float) -> list[dict]:
    spot = _spot(symbol, day)
    if spot is None:
        return []
    for expiry in _expiry_candidates(contracts, day, dte, 7, 50):
        if kind == "call":
            levels = [-0.05, 0.0, 0.05 + width]
            structure = "bwb_call_credit"
        else:
            levels = [-0.05 - width, -0.05, 0.0]
            structure = "bwb_put_credit"
        selected = [_select(contracts, expiry, kind, spot, level) for level in levels]
        if any(item is None for item in selected):
            continue
        if len({item["symbol"] for item in selected}) != 3:
            continue
        return [_leg(selected[0], symbol, 1, day, structure, dte, width), _leg(selected[1], symbol, -2, day, structure, dte, width), _leg(selected[2], symbol, 1, day, structure, dte, width)]
    return []


def _daily_spread_gate(contracts: list[dict], symbol: str, day: pd.Timestamp, dte: int, kind: str) -> list[dict]:
    """Materializa una pata candidata solo para medir cobertura.

    No se usa para declarar un backtest 0DTE válido: las barras cacheadas son
    diarias y no contienen quotes intradía ni cutoff.
    """
    spot = _spot(symbol, day)
    if spot is None:
        return []
    expiries = _expiry_candidates(contracts, day, dte, dte, dte)
    if not expiries:
        return []
    expiry = expiries[0]
    if kind == "put":
        short = _select(contracts, expiry, kind, spot, -0.02)
        long = _select(contracts, expiry, kind, spot, -0.05)
        structure = f"bull_put_{dte}dte"
    else:
        short = _select(contracts, expiry, kind, spot, 0.02)
        long = _select(contracts, expiry, kind, spot, 0.05)
        structure = f"bear_call_{dte}dte"
    if short is None or long is None or short["symbol"] == long["symbol"]:
        return []
    return [_leg(short, symbol, -1, day, structure, dte, 0.0), _leg(long, symbol, 1, day, structure, dte, 0.0)]


def main() -> None:
    source = json.loads(SOURCE_CONTRACTS.read_text(encoding="utf-8"))["all"]
    selected: dict[str, dict] = {}
    gate_counts = {"bwb": 0, "0dte": 0, "1dte": 0}
    for symbol in SYMBOLS:
        contracts = source.get(symbol, [])
        for day in _fridays():
            for dte in DTE_TARGETS:
                for width in WIDTHS:
                    for kind in ("call", "put"):
                        for leg in _bwb(contracts, symbol, day, kind, dte, width):
                            selected.setdefault(leg["symbol"], {key: leg[key] for key in ("symbol", "underlying", "type", "strike", "expiration")})
                            selected[leg["symbol"]].setdefault("uses", []).append({key: leg[key] for key in ("decision", "structure", "dte_target", "width", "quantity")})
                            gate_counts["bwb"] += 1
        for day in _all_days():
            for dte, name in ((0, "0dte"), (1, "1dte")):
                for kind in ("put", "call"):
                    for leg in _daily_spread_gate(contracts, symbol, day, dte, kind):
                        selected.setdefault(leg["symbol"], {key: leg[key] for key in ("symbol", "underlying", "type", "strike", "expiration")})
                        selected[leg["symbol"]].setdefault("uses", []).append({key: leg[key] for key in ("decision", "structure", "dte_target", "width", "quantity")})
                        gate_counts[name] += 1
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    symbols = sorted(selected)
    client = OptionHistoricalDataClient(os.environ["APCA_API_KEY_ID"], os.environ["APCA_API_SECRET_KEY"])
    frames = []
    for offset in range(0, len(symbols), 80):
        chunk = symbols[offset:offset + 80]
        request = OptionBarsRequest(symbol_or_symbols=chunk, start=START.to_pydatetime(), end=END.to_pydatetime(), timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Day), limit=10000)
        result = client.get_option_bars(request)
        if len(result.df):
            frames.append(result.df)
    bars = pd.concat(frames).sort_index() if frames else pd.DataFrame()
    bars.to_pickle(OUT_DIR / "option_bars.pkl")
    (OUT_DIR / "selected_contracts.json").write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
    manifest = {"source": "Alpaca historical option contracts and daily OHLC bars; read-only", "symbols": SYMBOLS, "start": START.isoformat(), "end": END.isoformat(), "bwb_candidate_legs": gate_counts["bwb"], "zero_dte_candidate_legs": gate_counts["0dte"], "one_dte_candidate_legs": gate_counts["1dte"], "selected_contracts": len(selected), "contracts_with_bars": len(set(bars.index.get_level_values(0))) if isinstance(bars.index, pd.MultiIndex) and len(bars) else 0, "bars_rows": len(bars), "intraday_bid_ask_available": False, "decision": "BWB may be described with daily proxy; 0DTE/1DTE requires intraday quotes and is data-gated.", "lookahead_note": "Historical chain membership and listing timestamps are not available; RESEARCH_ONLY."}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
