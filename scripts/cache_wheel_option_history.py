"""Cachea contratos y barras históricas reales para una Wheel experimental.

La descarga es solo de datos de mercado; nunca coloca órdenes. La selección de
contratos usa vencimiento y moneyness observables al día de decisión, pero no
pretende reconstruir delta histórica si el proveedor no la entrega as-of.
"""
from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import pandas as pd
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.requests import OptionBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import AssetStatus
from alpaca.trading.requests import GetOptionContractsRequest

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", "/home/ubuntu/backtests/setup_history"))
OUT_DIR = Path(os.environ.get("WHEEL_HISTORY_DIR", "/home/ubuntu/backtests/wheel_option_history_2026-08-18"))
SYMBOLS = ["AMD", "BB", "F", "NOK", "PLTR", "TQQQ", "TSLA"]
START = pd.Timestamp("2026-04-01", tz="UTC")
END = pd.Timestamp("2026-08-15", tz="UTC")
EXPIRY_MIN = date(2026, 4, 1)
EXPIRY_MAX = date(2026, 10, 31)


def _fridays() -> list[pd.Timestamp]:
    days = pd.date_range(START, END, freq="D")
    return [d for d in days if d.weekday() == 4]


def _spot(symbol: str, day: pd.Timestamp) -> float | None:
    path = HISTORY_DIR / f"{symbol}.pkl"
    if not path.exists():
        return None
    df = pd.read_pickle(path)
    rows = df[df.index.normalize() == day]
    return float(rows["close"].iloc[-1]) if len(rows) else None


def _step(spot: float) -> float:
    if spot < 25:
        return 0.5
    if spot < 100:
        return 1.0
    if spot < 300:
        return 2.5
    return 5.0


def _load_contracts(client: TradingClient, symbol: str) -> list[dict]:
    out: dict[str, dict] = {}
    for status in [AssetStatus.ACTIVE, AssetStatus.INACTIVE]:
        page_token = None
        while True:
            req = GetOptionContractsRequest(
                underlying_symbols=[symbol],
                status=status,
                expiration_date_gte=EXPIRY_MIN,
                expiration_date_lte=EXPIRY_MAX,
                limit=1000,
                page_token=page_token,
            )
            response = client.get_option_contracts(req)
            for c in response.option_contracts:
                if c.symbol in out:
                    continue
                out[c.symbol] = {
                    "symbol": c.symbol,
                    "underlying": c.underlying_symbol,
                    "type": c.type.value,
                    "strike": float(c.strike_price),
                    "expiration": c.expiration_date.isoformat(),
                    "status": c.status.value,
                }
            page_token = response.next_page_token
            if not page_token:
                break
    return list(out.values())


def _select_contract(contracts: list[dict], symbol: str, day: pd.Timestamp, kind: str, otm: float) -> dict | None:
    spot = _spot(symbol, day)
    if spot is None:
        return None
    target_exp = day + pd.Timedelta(days=30)
    eligible = []
    for c in contracts:
        expiry = pd.Timestamp(c["expiration"], tz="UTC")
        dte = (expiry - day).days
        if c["type"] != ("put" if kind == "P" else "call") or not 21 <= dte <= 45:
            continue
        target_strike = spot * (1.0 - otm) if kind == "P" else spot * (1.0 + otm)
        eligible.append((abs((expiry - target_exp).days) * 10000 + abs(c["strike"] - target_strike), c))
    return min(eligible, key=lambda x: x[0])[1] if eligible else None


def _contract_symbols(contracts_by_symbol: dict[str, list[dict]]) -> dict[str, dict]:
    selected = {}
    for symbol, contracts in contracts_by_symbol.items():
        for day in _fridays():
            for kind, otm in [("P", 0.05), ("P", 0.10), ("C", 0.05), ("C", 0.10)]:
                c = _select_contract(contracts, symbol, day, kind, otm)
                if c:
                    key = c["symbol"]
                    selected[key] = {**c, "selected_for": []}
                    selected[key]["selected_for"].append({"symbol": symbol, "decision": day.date().isoformat(), "kind": kind, "otm": otm})
    return selected


def _fetch_bars(client: OptionHistoricalDataClient, symbols: list[str]) -> pd.DataFrame:
    frames = []
    for start in range(0, len(symbols), 80):
        chunk = symbols[start:start + 80]
        req = OptionBarsRequest(
            symbol_or_symbols=chunk,
            start=START.to_pydatetime(),
            end=END.to_pydatetime(),
            timeframe=TimeFrame(amount=1, unit=TimeFrameUnit.Day),
            limit=10000,
        )
        bar_set = client.get_option_bars(req)
        if len(bar_set.df):
            frames.append(bar_set.df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames).sort_index()


def main() -> None:
    key = os.environ["APCA_API_KEY_ID"]
    secret = os.environ["APCA_API_SECRET_KEY"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    trading = TradingClient(key, secret, paper=True)
    market = OptionHistoricalDataClient(key, secret)
    contracts_by_symbol = {symbol: _load_contracts(trading, symbol) for symbol in SYMBOLS}
    selected = _contract_symbols(contracts_by_symbol)
    bars = _fetch_bars(market, sorted(selected))
    bars.to_pickle(OUT_DIR / "option_bars.pkl")
    (OUT_DIR / "contracts.json").write_text(json.dumps({"all": contracts_by_symbol, "selected": selected}, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "source": "Alpaca historical option bars and option contracts API; read-only",
        "symbols": SYMBOLS,
        "start": START.isoformat(),
        "end": END.isoformat(),
        "decision_days": [d.date().isoformat() for d in _fridays()],
        "contracts_selected": len(selected),
        "contracts_with_bars": len(set(bars.index.get_level_values(0))) if isinstance(bars.index, pd.MultiIndex) and len(bars) else 0,
        "bars_rows": len(bars),
        "strike_selection": "nearest available strike to 5% or 10% OTM target; expiration 21-45 DTE nearest 30 days",
        "delta_note": "historical delta unavailable as-of; moneyness is a declared proxy, not delta",
        "lookahead_note": "contract inventory lacks listing timestamp; candidate must have historical bars on entry and this limitation remains",
    }
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
