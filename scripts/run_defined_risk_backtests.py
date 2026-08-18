"""Backtest de estrategias de opciones con riesgo definido.

Usa barras históricas reales de Alpaca cacheadas por
cache_defined_risk_option_history.py. No coloca órdenes. La selección de
contratos por moneyness es un proxy porque el delta histórico point-in-time no
está disponible.
"""
from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", "/home/ubuntu/backtests/setup_history"))
OPTION_DIR = Path(os.environ.get("DEFINED_RISK_HISTORY_DIR", "/home/ubuntu/backtests/defined_risk_option_history_2026-08-18"))
OUT = Path(os.environ.get("DEFINED_RISK_BACKTEST_OUT", "/home/ubuntu/backtests/defined_risk_backtests_2026-08-18"))
CAPITAL = float(os.environ.get("DEFINED_RISK_CAPITAL", "100000"))
COMMISSION = 0.65
SYMBOLS = ["AMD", "BB", "F", "NOK", "PLTR", "TQQQ", "TSLA"]
WINDOWS = {
    "spring_selloff": ("2026-04-01", "2026-04-30"),
    "early_recovery": ("2026-05-01", "2026-05-31"),
    "summer_trend": ("2026-06-01", "2026-08-07"),
    "latest_30d": ("2026-07-01", "2026-08-07"),
    "full_recent": ("2026-04-01", "2026-08-07"),
}
STRUCTURES = ["bull_call_debit", "bear_put_debit", "bull_put_credit", "bear_call_credit", "iron_condor", "call_butterfly", "call_calendar", "put_calendar", "call_diagonal", "put_diagonal"]
DTE_TARGETS = [14, 30, 45]
WIDTHS = [0.05, 0.10]
MANAGEMENT = {
    "conservative": {"risk_pct": 0.005, "tp_pct": 0.50, "stop_pct": 0.50, "close_dte": 7, "slippage": 0.02},
    "base": {"risk_pct": 0.010, "tp_pct": 0.50, "stop_pct": 0.75, "close_dte": 7, "slippage": 0.05},
    "aggressive": {"risk_pct": 0.020, "tp_pct": 0.75, "stop_pct": 1.00, "close_dte": 0, "slippage": 0.10},
}
REGIME_MODES = ["gated", "neutral_ok"]


@dataclass
class Position:
    symbol: str
    structure: str
    legs: list[dict]
    entry_day: pd.Timestamp
    expiration: pd.Timestamp
    entry_net: float
    max_loss: float
    max_profit: float
    contracts: int


@dataclass
class Account:
    cash: float = CAPITAL
    positions: list[Position] = field(default_factory=list)
    realized: list[float] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    data_gaps: int = 0
    max_loss_hits: int = 0
    commissions: float = 0.0


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _daily_row(df: pd.DataFrame, day: pd.Timestamp):
    rows = df[df.index.normalize() == day.normalize()]
    return rows.iloc[-1] if len(rows) else None


def _option_frame(bars: pd.DataFrame, symbol: str) -> pd.DataFrame:
    try:
        out = bars.xs(symbol, level="symbol").copy()
    except KeyError:
        return pd.DataFrame()
    out.index = pd.DatetimeIndex(out.index).tz_convert("UTC")
    return out.sort_index()


def _option_value(bars_by_contract: dict[str, pd.DataFrame], contract: str, day: pd.Timestamp, strike: float, kind: str, spot: float, account: Account) -> float:
    df = bars_by_contract.get(contract)
    if df is not None and len(df):
        rows = df[df.index.normalize() == day.normalize()]
        if len(rows) and float(rows["close"].iloc[-1]) > 0:
            return float(rows["close"].iloc[-1])
    account.data_gaps += 1
    return max(spot - strike, 0.0) if kind == "call" else max(strike - spot, 0.0)


def _entry_bar(bars_by_contract: dict[str, pd.DataFrame], contract: str, decision: pd.Timestamp):
    df = bars_by_contract.get(contract)
    if df is None or df.empty:
        return None, None
    rows = df[df.index.normalize() > decision.normalize()]
    if rows.empty:
        return None, None
    day = rows.index[0].normalize()
    if (day - decision.normalize()).days > 5:
        return None, None
    return rows.iloc[0], day


def _regime(df: pd.DataFrame, day: pd.Timestamp) -> str:
    rows = df[df.index.normalize() <= day.normalize()]
    if len(rows) < 20:
        return "neutral"
    close = rows["close"].astype(float)
    sma20 = float(close.tail(20).mean())
    ret5 = float(close.iloc[-1] / close.iloc[-6] - 1.0) if len(close) >= 6 else 0.0
    if close.iloc[-1] > sma20 and ret5 > 0:
        return "bull"
    if close.iloc[-1] < sma20 and ret5 < 0:
        return "bear"
    return "neutral"


def _allowed(structure: str, regime: str, mode: str) -> bool:
    if mode == "neutral_ok":
        if structure in {"bull_call_debit", "bull_put_credit"}:
            return regime in {"bull", "neutral"}
        if structure in {"bear_put_debit", "bear_call_credit"}:
            return regime in {"bear", "neutral"}
        return regime == "neutral"
    if structure in {"bull_call_debit", "bull_put_credit"}:
        return regime == "bull"
    if structure in {"bear_put_debit", "bear_call_credit"}:
        return regime == "bear"
    return regime == "neutral"


def _group_uses(selected: dict[str, dict]) -> dict[tuple, list[dict]]:
    groups: dict[tuple, list[dict]] = {}
    for metadata in selected.values():
        for use in metadata.get("uses", []):
            key = (use["decision"], use["structure"], int(use["dte_target"]), float(use["width"]), metadata["underlying"])
            groups.setdefault(key, []).append({"symbol": metadata["symbol"], "type": metadata["type"], "strike": float(metadata["strike"]), "expiration": metadata["expiration"], "quantity": int(use["quantity"]), "underlying": metadata["underlying"]})
    return groups


def _risk_profile(legs: list[dict], prices: dict[str, float]) -> tuple[float, float, float]:
    net = sum(leg["quantity"] * prices[leg["symbol"]] for leg in legs)
    strikes = {leg["strike"] for leg in legs}
    width = (max(strikes) - min(strikes)) * 100.0
    structure = legs[0].get("structure", "")
    if "calendar" in structure or "diagonal" in structure:
        debit = max(net * 100.0, 0.01)
        return net, debit, debit * 2.0
    if "iron_condor" in structure:
        puts = sorted([leg["strike"] for leg in legs if leg["type"] == "put"])
        calls = sorted([leg["strike"] for leg in legs if leg["type"] == "call"])
        wing = max(puts[-1] - puts[0], calls[-1] - calls[0]) * 100.0
        credit = max(-net * 100.0, 0.0)
        return net, max(wing - credit, 0.01), credit
    if "butterfly" in legs[0].get("structure", ""):
        ordered = sorted(strikes)
        wing = min(ordered[1] - ordered[0], ordered[2] - ordered[1]) * 100.0 if len(ordered) == 3 else width
        debit = max(net * 100.0, 0.01)
        return net, debit, max(wing - debit, 0.0)
    if net >= 0:
        return net, max(net * 100.0, 0.01), max(width - net * 100.0, 0.0)
    credit = -net * 100.0
    return net, max(width - credit, 0.01), credit


def _build_candidate(key: tuple, legs: list[dict], bars_by_contract: dict[str, pd.DataFrame], decision: pd.Timestamp, scenario: dict, symbol: str):
    prices = {}
    entry_days = []
    for leg in legs:
        bar, entry_day = _entry_bar(bars_by_contract, leg["symbol"], decision)
        if bar is None or float(bar.get("open", 0.0)) <= 0:
            return None
        raw = float(bar["open"])
        prices[leg["symbol"]] = raw * (1.0 + scenario["slippage"] if leg["quantity"] > 0 else 1.0 - scenario["slippage"])
        entry_days.append(entry_day)
    if len(set(entry_days)) != 1:
        return None
    net, max_loss, max_profit = _risk_profile(legs, prices)
    if max_loss <= 0:
        return None
    expiration = min(_ts(leg["expiration"]) for leg in legs)
    return Position(symbol=symbol, structure=key[1], legs=legs, entry_day=entry_days[0], expiration=expiration, entry_net=net, max_loss=max_loss, max_profit=max_profit, contracts=0)


def _close(account: Account, pos: Position, day: pd.Timestamp, underlyings: dict[str, pd.DataFrame], bars_by_contract: dict[str, pd.DataFrame], scenario: dict, reason: str) -> None:
    row = _daily_row(underlyings[pos.symbol], day)
    if row is None:
        return
    spot = float(row["close"])
    close_net = 0.0
    for leg in pos.legs:
        value = _option_value(bars_by_contract, leg["symbol"], day, leg["strike"], leg["type"], spot, account)
        fill = value * (1.0 - scenario["slippage"] if leg["quantity"] > 0 else 1.0 + scenario["slippage"])
        close_net += leg["quantity"] * fill
        account.cash += leg["quantity"] * fill * 100.0 * pos.contracts
    fee = COMMISSION * sum(abs(leg["quantity"]) for leg in pos.legs) * pos.contracts
    account.cash -= fee
    account.commissions += fee
    pnl = (-pos.entry_net + close_net) * 100.0 * pos.contracts - fee
    account.realized.append(pnl)
    if pnl <= -pos.max_loss * pos.contracts * 0.99:
        account.max_loss_hits += 1
    account.events.append({"day": day, "event": "close", "symbol": pos.symbol, "reason": reason, "contracts": pos.contracts, "pnl": pnl})


def _mark(account: Account, day: pd.Timestamp, underlyings: dict[str, pd.DataFrame], bars_by_contract: dict[str, pd.DataFrame]) -> float:
    equity = account.cash
    for pos in account.positions:
        row = _daily_row(underlyings[pos.symbol], day)
        if row is None:
            continue
        spot = float(row["close"])
        value = sum(leg["quantity"] * _option_value(bars_by_contract, leg["symbol"], day, leg["strike"], leg["type"], spot, account) for leg in pos.legs)
        equity += value * 100.0 * pos.contracts
    return equity


def _buy_hold(underlyings: dict[str, pd.DataFrame], start: str, end: str) -> float:
    values = []
    for df in underlyings.values():
        first = df[df.index.normalize() >= _ts(start)]
        last = df[df.index.normalize() <= _ts(end)]
        if len(first) and len(last):
            values.append(float(last["close"].iloc[-1]) / float(first["close"].iloc[0]))
    return (sum(values) / len(values) - 1.0) * 100.0 if values else 0.0


def _run(underlyings, groups, bars_by_contract, structure, dte, width, management, regime_mode, start, end):
    scenario = MANAGEMENT[management]
    account = Account()
    dates = sorted({_ts(d) for df in underlyings.values() for d in df.index.normalize() if _ts(start) <= _ts(d) <= _ts(end)})
    for day in dates:
        for pos in list(account.positions):
            if day >= pos.expiration.normalize():
                _close(account, pos, day, underlyings, bars_by_contract, scenario, "expiration")
                account.positions.remove(pos)
                continue
            row = _daily_row(underlyings[pos.symbol], day)
            if row is None:
                continue
            spot = float(row["close"])
            value = sum(leg["quantity"] * _option_value(bars_by_contract, leg["symbol"], day, leg["strike"], leg["type"], spot, account) for leg in pos.legs)
            pnl = (-pos.entry_net + value) * 100.0 * pos.contracts
            if pos.max_profit > 0 and pnl >= pos.max_profit * pos.contracts * scenario["tp_pct"]:
                _close(account, pos, day, underlyings, bars_by_contract, scenario, "take_profit")
                account.positions.remove(pos)
            elif pnl <= -pos.max_loss * pos.contracts * scenario["stop_pct"]:
                _close(account, pos, day, underlyings, bars_by_contract, scenario, "stop_loss")
                account.positions.remove(pos)
            elif scenario["close_dte"] and (pos.expiration - day).days <= scenario["close_dte"]:
                _close(account, pos, day, underlyings, bars_by_contract, scenario, "close_dte")
                account.positions.remove(pos)
        if day.weekday() == 4:
            for symbol in SYMBOLS:
                if symbol not in underlyings or any(pos.symbol == symbol for pos in account.positions):
                    continue
                row = _daily_row(underlyings[symbol], day)
                if row is None or not _allowed(structure, _regime(underlyings[symbol], day), regime_mode):
                    continue
                key = (day.date().isoformat(), structure, dte, width, symbol)
                legs = groups.get(key, [])
                if not legs:
                    continue
                candidate = _build_candidate(key, legs, bars_by_contract, day, scenario, symbol)
                if candidate is None:
                    continue
                risk_budget = max(account.cash, 0.0) * scenario["risk_pct"]
                qty = min(5, int(math.floor(risk_budget / candidate.max_loss)))
                if qty <= 0:
                    continue
                debit_cost = max(candidate.entry_net, 0.0) * 100.0 * qty
                if debit_cost > account.cash:
                    continue
                fee = COMMISSION * sum(abs(leg["quantity"]) for leg in legs) * qty
                if debit_cost + fee > account.cash:
                    continue
                account.cash -= candidate.entry_net * 100.0 * qty
                account.cash -= fee
                account.commissions += fee
                candidate.contracts = qty
                account.positions.append(candidate)
                account.events.append({"day": candidate.entry_day, "event": "open", "symbol": symbol, "contracts": qty, "entry_net": candidate.entry_net, "max_loss": candidate.max_loss})
        account.events.append({"day": day, "event": "mark", "equity": _mark(account, day, underlyings, bars_by_contract), "open_positions": len(account.positions)})
    if dates:
        for pos in list(account.positions):
            _close(account, pos, dates[-1], underlyings, bars_by_contract, scenario, "window_end")
            account.positions.remove(pos)
    curve = pd.DataFrame([e for e in account.events if e.get("event") == "mark"])
    final_equity = account.cash
    if len(curve):
        curve["equity"] = curve["equity"].astype(float)
        drawdown = ((curve["equity"] / curve["equity"].cummax()) - 1.0).min() * 100.0
    else:
        drawdown = 0.0
    wins = [p for p in account.realized if p > 0]
    losses = [p for p in account.realized if p < 0]
    result = {"return_pct": (final_equity / CAPITAL - 1.0) * 100.0, "pnl_usd": final_equity - CAPITAL, "max_drawdown_pct": drawdown, "closed_trades": len(account.realized), "win_rate_pct": (len(wins) / len(account.realized) * 100.0) if account.realized else 0.0, "profit_factor": sum(wins) / abs(sum(losses)) if losses else (float("inf") if wins else 0.0), "max_loss_hits": account.max_loss_hits, "data_gaps": account.data_gaps, "commissions": account.commissions, "buy_hold_return_pct": _buy_hold(underlyings, start, end), "ending_equity": final_equity, "open_positions_end": len(account.positions)}
    return result, curve, pd.DataFrame([e for e in account.events if e.get("event") in {"open", "close"}])


def main() -> None:
    underlyings = {}
    for symbol in SYMBOLS:
        path = HISTORY_DIR / f"{symbol}.pkl"
        if path.exists():
            df = pd.read_pickle(path).copy()
            df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
            underlyings[symbol] = df.sort_index()
    bars = pd.read_pickle(OPTION_DIR / "option_bars.pkl")
    bars_by_contract = {symbol: _option_frame(bars, symbol) for symbol in set(bars.index.get_level_values(0))}
    selected = json.loads((OPTION_DIR / "selected_contracts.json").read_text(encoding="utf-8"))
    groups = _group_uses(selected)
    rows, curves, events = [], [], []
    for structure in STRUCTURES:
        for dte in DTE_TARGETS:
            for width in WIDTHS:
                for management in MANAGEMENT:
                    for regime_mode in REGIME_MODES:
                        for window, (start, end) in WINDOWS.items():
                            metrics, curve, event_df = _run(underlyings, groups, bars_by_contract, structure, dte, width, management, regime_mode, start, end)
                            row = {"structure": structure, "dte_target": dte, "width": width, "management": management, "regime_mode": regime_mode, "window": window, "start": start, "end": end, **metrics}
                            rows.append(row)
                            if len(curve):
                                curve.insert(0, "structure", structure); curve.insert(1, "dte_target", dte); curve.insert(2, "width", width); curve.insert(3, "management", management); curve.insert(4, "regime_mode", regime_mode); curve.insert(5, "window", window); curves.append(curve)
                            if len(event_df):
                                event_df.insert(0, "structure", structure); event_df.insert(1, "dte_target", dte); event_df.insert(2, "width", width); event_df.insert(3, "management", management); event_df.insert(4, "regime_mode", regime_mode); event_df.insert(5, "window", window); events.append(event_df)
    result = pd.DataFrame(rows)
    result.to_csv(f"{OUT}_results.csv", index=False)
    pd.concat(curves, ignore_index=True).to_csv(f"{OUT}_equity_curves.csv", index=False) if curves else Path(f"{OUT}_equity_curves.csv").write_text("\n", encoding="utf-8")
    pd.concat(events, ignore_index=True).to_csv(f"{OUT}_events.csv", index=False) if events else Path(f"{OUT}_events.csv").write_text("\n", encoding="utf-8")
    manifest = {"source": "Alpaca historical option OHLC bars and cached underlying OHLCV; no synthetic data", "capital": CAPITAL, "commission_per_contract_per_side": COMMISSION, "structures": STRUCTURES, "dte_targets": DTE_TARGETS, "widths": WIDTHS, "management": MANAGEMENT, "regime_modes": REGIME_MODES, "windows": WINDOWS, "max_contracts_per_symbol": 5, "entry": "weekly Friday decision using closed underlying data; fill at first option bar after decision within 5 calendar days", "pricing": "option OHLC with side-aware slippage; intrinsic fallback when daily bar absent", "delta_note": "moneyness proxy, not historical delta", "lookahead_note": "historical listing timestamp and chain membership unavailable; RESEARCH_ONLY", "results_csv": f"{OUT}_results.csv"}
    Path(f"{OUT}_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"rows={len(result)}")
    print(result.sort_values("return_pct", ascending=False).head(20).to_string(index=False))


if __name__ == "__main__":
    main()
