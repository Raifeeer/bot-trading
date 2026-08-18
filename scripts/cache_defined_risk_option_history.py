"""Cachea contratos y barras para estrategias de opciones de riesgo definido."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", "/home/ubuntu/backtests/setup_history"))
SOURCE_CONTRACTS = Path(os.environ.get("WHEEL_CONTRACTS", "/home/ubuntu/backtests/wheel_option_history_2026-08-18/contracts.json"))
OUT_DIR = Path(os.environ.get("DEFINED_RISK_HISTORY_DIR", "/home/ubuntu/backtests/defined_risk_option_history_2026-08-18"))
SYMBOLS = ["AMD", "BB", "F", "NOK", "PLTR", "TQQQ", "TSLA"]
START = pd.Timestamp("2026-04-01", tz="UTC")
END = pd.Timestamp("2026-08-07", tz="UTC")
DTE_TARGETS = [14, 30, 45]
MONEYNESS_LEVELS = [-0.10, -0.05, 0.0, 0.05, 0.10, 0.15]


def _fridays() -> list[pd.Timestamp]:
    return [d for d in pd.date_range(START, END, freq="D") if d.weekday() == 4]


def _spot(symbol: str, day: pd.Timestamp) -> float | None:
    path = HISTORY_DIR / f"{symbol}.pkl"
    if not path.exists():
        return None
    df = pd.read_pickle(path)
    rows = df[df.index.normalize() == day]
    return float(rows["close"].iloc[-1]) if len(rows) else None


def _nearest_expirations(contracts: list[dict], day: pd.Timestamp, dte_target: int) -> list[str]:
    exps = set()
    target = day + pd.Timedelta(days=dte_target)
    for c in contracts:
        exp = pd.Timestamp(c["expiration"], tz="UTC")
        dte = (exp - day).days
        if 7 <= dte <= 50:
            exps.add(c["expiration"])
    return sorted(exps, key=lambda e: abs((pd.Timestamp(e, tz="UTC") - target).days))


def _select_at_expiry(contracts: list[dict], expiry: str, kind: str, spot: float, moneyness: float) -> dict | None:
    target = spot * (1.0 + moneyness) if kind == "call" else spot * (1.0 - moneyness)
    cands = [c for c in contracts if c["expiration"] == expiry and c["type"] == kind]
    return min(cands, key=lambda c: abs(float(c["strike"]) - target)) if cands else None


def _structure_levels(name: str, width: float) -> list[tuple[str, float, int]]:
    if name == "bull_call_debit":
        return [("call", -width, 1), ("call", 0.0, -1)]
    if name == "bear_put_debit":
        return [("put", -width, 1), ("put", 0.0, -1)]
    if name == "bull_put_credit":
        return [("put", 0.05, -1), ("put", 0.05 + width, 1)]
    if name == "bear_call_credit":
        return [("call", 0.05, -1), ("call", 0.05 + width, 1)]
    if name == "iron_condor":
        return [("put", 0.05, -1), ("put", 0.05 + width, 1), ("call", 0.05, -1), ("call", 0.05 + width, 1)]
    if name == "call_butterfly":
        return [("call", -width, 1), ("call", 0.0, -2), ("call", width, 1)]
    raise ValueError(name)


def _select_structure(contracts: list[dict], symbol: str, day: pd.Timestamp, name: str, dte: int, width: float) -> list[dict]:
    spot = _spot(symbol, day)
    if spot is None:
        return []
    if name in {"call_calendar", "put_calendar", "call_diagonal", "put_diagonal"}:
        kind = "call" if name.startswith("call") else "put"
        near_expiries = _nearest_expirations(contracts, day, 14)
        far_expiries = _nearest_expirations(contracts, day, dte)
        for near_exp in near_expiries:
            for far_exp in far_expiries:
                if near_exp == far_exp:
                    continue
                near_target = 0.0
                far_target = (-width if kind == "call" else width) if "diagonal" in name else 0.0
                near = _select_at_expiry(contracts, near_exp, kind, spot, near_target)
                far = _select_at_expiry(contracts, far_exp, kind, spot, far_target)
                if near and far:
                    return [
                        {"symbol": far["symbol"], "underlying": symbol, "type": kind, "strike": float(far["strike"]), "expiration": far_exp, "quantity": 1, "decision": day.date().isoformat(), "dte_target": dte, "width": width, "structure": name},
                        {"symbol": near["symbol"], "underlying": symbol, "type": kind, "strike": float(near["strike"]), "expiration": near_exp, "quantity": -1, "decision": day.date().isoformat(), "dte_target": dte, "width": width, "structure": name},
                    ]
        return []
    levels = _structure_levels(name, width)
    for expiry in _nearest_expirations(contracts, day, dte):
        legs = []
        ok = True
        for kind, moneyness, quantity in levels:
            leg = _select_at_expiry(contracts, expiry, kind, spot, moneyness)
            if leg is None:
                ok = False
                break
            legs.append({"symbol": leg["symbol"], "underlying": symbol, "type": kind, "strike": float(leg["strike"]), "expiration": expiry, "quantity": quantity, "decision": day.date().isoformat(), "dte_target": dte, "width": width, "structure": name})
        if ok:
            return legs
    return []


def main() -> None:
    source = json.loads(SOURCE_CONTRACTS.read_text(encoding="utf-8"))["all"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    contracts_by_symbol = {symbol: source.get(symbol, []) for symbol in SYMBOLS}
    structures = ["bull_call_debit", "bear_put_debit", "bull_put_credit", "bear_call_credit", "iron_condor", "call_butterfly", "call_calendar", "put_calendar", "call_diagonal", "put_diagonal"]
    selected: dict[str, dict] = {}
    for symbol, contracts in contracts_by_symbol.items():
        for day in _fridays():
            for structure in structures:
                for dte in DTE_TARGETS:
                    for width in [0.05, 0.10]:
                        legs = _select_structure(contracts, symbol, day, structure, dte, width)
                        for leg in legs:
                            selected.setdefault(leg["symbol"], {"symbol": leg["symbol"], "underlying": symbol, "type": leg["type"], "strike": leg["strike"], "expiration": leg["expiration"], "uses": []})
                            selected[leg["symbol"]]["uses"].append({"decision": leg["decision"], "structure": structure, "dte_target": dte, "width": width, "quantity": leg["quantity"]})
    client = OptionHistoricalDataClient(os.environ["APCA_API_KEY_ID"], os.environ["APCA_API_SECRET_KEY"])
    frames = []
    symbols = sorted(selected)
    for offset in range(0, len(symbols), 80):
        chunk = symbols[offset:offset + 80]
        req = OptionBarsRequest(symbol_or_symbols=chunk, start=START.to_pydatetime(), end=END.to_pydatetime(), timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Day), limit=10000)
        bar_set = client.get_option_bars(req)
        if len(bar_set.df):
            frames.append(bar_set.df)
    bars = pd.concat(frames).sort_index() if frames else pd.DataFrame()
    bars.to_pickle(OUT_DIR / "option_bars.pkl")
    (OUT_DIR / "selected_contracts.json").write_text(json.dumps(selected, indent=2) + "\n", encoding="utf-8")
    manifest = {"source": "Alpaca historical option contracts and daily option bars; read-only", "symbols": SYMBOLS, "start": START.isoformat(), "end": END.isoformat(), "decision_days": [d.date().isoformat() for d in _fridays()], "structures": structures, "dte_targets": DTE_TARGETS, "widths": [0.05, 0.10], "moneyness_levels": MONEYNESS_LEVELS, "selected_contracts": len(selected), "contracts_with_bars": len(set(bars.index.get_level_values(0))) if isinstance(bars.index, pd.MultiIndex) and len(bars) else 0, "bars_rows": len(bars), "delta_note": "Historical point-in-time delta was unavailable; moneyness is a declared strike proxy.", "lookahead_note": "Contract listing timestamp and historical chain membership are not available; results are research-only."}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
