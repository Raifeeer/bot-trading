"""Backtest experimental de The Wheel con barras históricas de opciones Alpaca.

El motor es deliberadamente conservador en sus afirmaciones: usa OHLC diarios
de opciones, no quotes bid/ask ni deltas históricos point-in-time. La selección
por moneyness es un proxy declarado. No coloca órdenes y no toca producción.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = Path(os.environ.get("SETUP_HISTORY_DIR", "/home/ubuntu/backtests/setup_history"))
OPTION_DIR = Path(os.environ.get("WHEEL_HISTORY_DIR", "/home/ubuntu/backtests/wheel_option_history_2026-08-18"))
OUT = Path(os.environ.get("WHEEL_BACKTEST_OUT", "/home/ubuntu/backtests/wheel_backtests_2026-08-18"))
SYMBOLS = ["AMD", "BB", "F", "NOK", "PLTR", "TQQQ", "TSLA"]
CAPITAL = float(os.environ.get("WHEEL_CAPITAL", "100000"))
COMMISSION = 0.65
WINDOWS = {
    "spring_selloff": ("2026-04-01", "2026-04-30"),
    "early_recovery": ("2026-05-01", "2026-05-31"),
    "summer_trend": ("2026-06-01", "2026-08-07"),
    "latest_30d": ("2026-07-01", "2026-08-07"),
    "full_recent": ("2026-04-01", "2026-08-07"),
}
SCENARIOS = {
    "wheel_conservative": {"put_otm": 0.10, "call_otm": 0.10, "take_profit": 0.50, "roll": False, "max_collateral_pct": 0.25, "slippage_pct": 0.02},
    "wheel_base": {"put_otm": 0.05, "call_otm": 0.05, "take_profit": 0.50, "roll": False, "max_collateral_pct": 0.50, "slippage_pct": 0.05},
    "wheel_early_profit": {"put_otm": 0.10, "call_otm": 0.10, "take_profit": 0.75, "roll": False, "max_collateral_pct": 0.50, "slippage_pct": 0.05},
    "wheel_roll_defense": {"put_otm": 0.10, "call_otm": 0.10, "take_profit": 0.50, "roll": True, "max_collateral_pct": 0.50, "slippage_pct": 0.05},
    "wheel_stress": {"put_otm": 0.05, "call_otm": 0.05, "take_profit": None, "roll": False, "max_collateral_pct": 0.75, "slippage_pct": 0.10},
}


@dataclass
class Position:
    symbol: str
    phase: str
    contract: str
    strike: float
    expiration: pd.Timestamp
    entry_premium: float
    entry_day: pd.Timestamp
    shares: int = 0
    assigned_cost_basis: float | None = None
    rolls: int = 0
    data_gaps: int = 0


@dataclass
class Account:
    cash: float = CAPITAL
    positions: list[Position] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)
    data_gaps: int = 0
    assigned_count: int = 0
    expired_count: int = 0
    roll_count: int = 0
    tp_count: int = 0


def _ts(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _load_data() -> tuple[dict[str, pd.DataFrame], pd.DataFrame, dict]:
    underlyings = {}
    for symbol in SYMBOLS:
        path = HISTORY_DIR / f"{symbol}.pkl"
        if path.exists():
            df = pd.read_pickle(path).copy()
            df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
            underlyings[symbol] = df.sort_index()
    option_bars = pd.read_pickle(OPTION_DIR / "option_bars.pkl").sort_index()
    contracts = json.loads((OPTION_DIR / "contracts.json").read_text(encoding="utf-8"))
    return underlyings, option_bars, contracts["all"]


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


def _option_bar(bars_by_symbol: dict[str, pd.DataFrame], contract: str, day: pd.Timestamp):
    df = bars_by_symbol.get(contract)
    if df is None or df.empty:
        return None
    rows = df[df.index.normalize() == day.normalize()]
    return rows.iloc[-1] if len(rows) else None


def _first_bar_after(bars_by_symbol: dict[str, pd.DataFrame], contract: str, decision: pd.Timestamp):
    df = bars_by_symbol.get(contract)
    if df is None or df.empty:
        return None, None
    rows = df[df.index.normalize() > decision.normalize()]
    if rows.empty:
        return None, None
    return rows.iloc[0], rows.index[0].normalize()


def _next_trading_day(df: pd.DataFrame, day: pd.Timestamp):
    dates = pd.DatetimeIndex(df.index).normalize().unique().sort_values()
    later = dates[dates > day.normalize()]
    return later[0] if len(later) else None


def _select_contract(contracts: list[dict], bars_by_symbol: dict[str, pd.DataFrame], symbol: str, decision: pd.Timestamp, kind: str, otm: float):
    underlying = _daily_row(UNDERLYINGS[symbol], decision)
    if underlying is None:
        return None
    spot = float(underlying["close"])
    target_expiry = decision + pd.Timedelta(days=30)
    target_strike = spot * (1.0 - otm) if kind == "put" else spot * (1.0 + otm)
    candidates = []
    for contract in contracts:
        if contract["type"] != kind:
            continue
        expiry = _ts(contract["expiration"])
        dte = (expiry - decision).days
        if not 21 <= dte <= 45:
            continue
        bar, entry_day = _first_bar_after(bars_by_symbol, contract["symbol"], decision)
        if bar is None or float(bar.get("open", 0.0)) <= 0.0:
            continue
        score = abs((expiry - target_expiry).days) * 10000.0 + abs(float(contract["strike"]) - target_strike)
        candidates.append((score, contract, entry_day))
    return min(candidates, key=lambda item: item[0]) if candidates else None


def _trade(account: Account, day: pd.Timestamp, kind: str, pos: Position | None, contract: str, premium: float, qty: int, reason: str, slippage: float):
    fill = premium * (1.0 - slippage) if kind == "sell" else premium * (1.0 + slippage)
    amount = fill * 100 * qty
    fee = COMMISSION * qty
    account.cash += amount - fee if kind == "sell" else -amount - fee
    account.trades.append({"day": day, "symbol": pos.symbol if pos else "", "contract": contract, "action": kind, "premium": premium, "fill": fill, "qty": qty, "fee": fee, "reason": reason})
    return fill


def _intrinsic(pos: Position, spot: float) -> float:
    if pos.phase == "csp":
        return max(pos.strike - spot, 0.0)
    return max(spot - pos.strike, 0.0)


def _mark(account: Account, day: pd.Timestamp, underlyings: dict[str, pd.DataFrame], bars_by_symbol: dict[str, pd.DataFrame]) -> float:
    equity = account.cash
    for pos in account.positions:
        row = _daily_row(underlyings[pos.symbol], day)
        if row is None:
            continue
        spot = float(row["close"])
        if pos.shares:
            equity += pos.shares * spot
        if pos.phase in {"csp", "cc"}:
            bar = _option_bar(bars_by_symbol, pos.contract, day)
            option_value = float(bar["close"]) if bar is not None and float(bar.get("close", 0.0)) > 0 else _intrinsic(pos, spot)
            equity -= option_value * 100
    return equity


def _candidate_rank(candidate, underlyings, bars_by_symbol, decision):
    _, contract, entry_day = candidate
    row = _daily_row(underlyings[contract["underlying"]], decision)
    bar = _option_bar(bars_by_symbol, contract["symbol"], entry_day)
    if row is None or bar is None:
        return -1.0
    premium = float(bar["open"])
    return premium / max(float(contract["strike"]) * 100.0, 1.0)


def _open_covered_call(account: Account, day: pd.Timestamp, pos: Position, bars_by_symbol, contracts_by_symbol, scenario):
    candidate = _select_contract(contracts_by_symbol[pos.symbol], bars_by_symbol, pos.symbol, day, "call", scenario["call_otm"])
    if not candidate:
        return False
    _, contract, entry_day = candidate
    bar = _option_bar(bars_by_symbol, contract["symbol"], entry_day)
    if bar is None:
        return False
    premium = float(bar["open"])
    pos.phase = "cc"
    pos.contract = contract["symbol"]
    pos.strike = float(contract["strike"])
    pos.expiration = _ts(contract["expiration"])
    pos.entry_premium = _trade(account, entry_day, "sell", pos, pos.contract, premium, 1, "open_cc", scenario["slippage_pct"])
    pos.entry_day = entry_day
    account.events.append({"day": entry_day, "symbol": pos.symbol, "event": "open_cc", "contract": pos.contract, "premium": pos.entry_premium})
    return True


def _enter_next_week(account: Account, day: pd.Timestamp, underlyings, bars_by_symbol, contracts_by_symbol, scenario, phase: str, max_positions: int):
    if len(account.positions) >= max_positions:
        return
    candidates = []
    for symbol, contracts in contracts_by_symbol.items():
        if any(pos.symbol == symbol for pos in account.positions):
            continue
        kind = "put" if phase == "csp" else "call"
        otm = scenario["put_otm"] if kind == "put" else scenario["call_otm"]
        candidate = _select_contract(contracts, bars_by_symbol, symbol, day, kind, otm)
        if candidate:
            candidates.append(candidate)
    candidates.sort(key=lambda candidate: _candidate_rank(candidate, underlyings, bars_by_symbol, day), reverse=True)
    for _, contract, entry_day in candidates:
        if len(account.positions) >= max_positions:
            break
        bar = _option_bar(bars_by_symbol, contract["symbol"], entry_day)
        if bar is None:
            continue
        premium = float(bar["open"])
        strike = float(contract["strike"])
        reserved = sum(pos.strike * 100 for pos in account.positions if pos.phase == "csp")
        if phase == "csp" and reserved + strike * 100 > CAPITAL * scenario["max_collateral_pct"]:
            continue
        pos = Position(symbol=contract["underlying"], phase=phase, contract=contract["symbol"], strike=strike, expiration=_ts(contract["expiration"]), entry_premium=0.0, entry_day=entry_day)
        fill = _trade(account, entry_day, "sell", pos, pos.contract, premium, 1, f"open_{phase}", scenario["slippage_pct"])
        pos.entry_premium = fill
        if phase == "cc":
            pos.shares = 100
        account.positions.append(pos)
        account.events.append({"day": entry_day, "symbol": pos.symbol, "event": "open_" + phase, "contract": pos.contract, "premium": fill})


def _manage_positions(account: Account, day: pd.Timestamp, underlyings, bars_by_symbol, contracts_by_symbol, scenario):
    remaining = []
    for pos in account.positions:
        row = _daily_row(underlyings[pos.symbol], day)
        if row is None:
            remaining.append(pos)
            continue
        if pos.phase == "assigned_stock" and not pos.contract:
            remaining.append(pos)
            continue
        spot = float(row["close"])
        bar = _option_bar(bars_by_symbol, pos.contract, day)
        price = float(bar["close"]) if bar is not None and float(bar.get("close", 0.0)) > 0 else _intrinsic(pos, spot)
        if bar is None:
            account.data_gaps += 1
        dte = (pos.expiration - day).days
        if scenario["take_profit"] is not None and dte > 0 and price <= pos.entry_premium * (1.0 - scenario["take_profit"]):
            _trade(account, day, "buy", pos, pos.contract, price, 1, "take_profit", scenario["slippage_pct"])
            account.tp_count += 1
            account.events.append({"day": day, "symbol": pos.symbol, "event": "take_profit", "contract": pos.contract})
            remaining.append(Position(symbol=pos.symbol, phase="assigned_stock", contract="", strike=0.0, expiration=day, entry_premium=0.0, entry_day=day, shares=100, assigned_cost_basis=pos.assigned_cost_basis)) if pos.phase == "cc" else None
            continue
        if scenario["roll"] and dte > 7 and price >= pos.entry_premium * 2.0:
            _trade(account, day, "buy", pos, pos.contract, price, 1, "roll_close", scenario["slippage_pct"])
            replacement = _select_contract(contracts_by_symbol[pos.symbol], bars_by_symbol, pos.symbol, day, "put" if pos.phase == "csp" else "call", scenario["put_otm"] if pos.phase == "csp" else scenario["call_otm"])
            if replacement:
                _, contract, entry_day = replacement
                new_bar = _option_bar(bars_by_symbol, contract["symbol"], entry_day)
                if new_bar is not None:
                    new_pos = Position(symbol=pos.symbol, phase=pos.phase, contract=contract["symbol"], strike=float(contract["strike"]), expiration=_ts(contract["expiration"]), entry_premium=0.0, entry_day=entry_day, shares=pos.shares, assigned_cost_basis=pos.assigned_cost_basis, rolls=pos.rolls + 1)
                    new_pos.entry_premium = _trade(account, entry_day, "sell", new_pos, new_pos.contract, float(new_bar["open"]), 1, "roll_open", scenario["slippage_pct"])
                    remaining.append(new_pos)
                    account.roll_count += 1
                    account.events.append({"day": entry_day, "symbol": pos.symbol, "event": "roll_open", "contract": new_pos.contract})
                    continue
            if pos.phase == "cc":
                pos.phase = "assigned_stock"
                pos.contract = ""
                pos.strike = 0.0
                pos.expiration = day
                remaining.append(pos)
            account.roll_count += 1
            account.events.append({"day": day, "symbol": pos.symbol, "event": "roll_close_no_replacement", "contract": pos.contract})
            continue
        if day.normalize() >= pos.expiration.normalize():
            if pos.phase == "csp":
                if spot <= pos.strike:
                    account.cash -= pos.strike * 100
                    pos.phase = "assigned_stock"
                    pos.shares = 100
                    pos.assigned_cost_basis = pos.strike - pos.entry_premium
                    pos.contract = ""
                    pos.expiration = day
                    account.assigned_count += 1
                    account.events.append({"day": day, "symbol": pos.symbol, "event": "put_assigned", "strike": pos.strike, "cost_basis": pos.assigned_cost_basis})
                    remaining.append(pos)
                else:
                    account.expired_count += 1
                    account.events.append({"day": day, "symbol": pos.symbol, "event": "put_expired_worthless", "contract": pos.contract})
            else:
                if spot >= pos.strike:
                    account.cash += pos.strike * 100
                    account.events.append({"day": day, "symbol": pos.symbol, "event": "call_assigned", "strike": pos.strike})
                else:
                    pos.phase = "assigned_stock"
                    pos.contract = ""
                    pos.expiration = day
                    account.expired_count += 1
                    account.events.append({"day": day, "symbol": pos.symbol, "event": "call_expired_stock_retained"})
                    remaining.append(pos)
            continue
        remaining.append(pos)
    account.positions = remaining


def _buy_hold(underlyings: dict[str, pd.DataFrame], start: str, end: str) -> float:
    values = []
    for _symbol, df in underlyings.items():
        first = df[df.index.normalize() >= _ts(start)]
        last = df[df.index.normalize() <= _ts(end)]
        if len(first) and len(last):
            values.append(float(last["close"].iloc[-1]) / float(first["close"].iloc[0]))
    return (sum(values) / len(values) - 1.0) * 100.0 if values else 0.0


def _run_window(underlyings, bars_by_symbol, contracts_by_symbol, start: str, end: str, scenario: dict) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    account = Account()
    dates = sorted({_ts(d) for df in underlyings.values() for d in df.index.normalize() if _ts(start) <= _ts(d) <= _ts(end)})
    if not dates:
        return {}, pd.DataFrame(), pd.DataFrame()
    for day in dates:
        _manage_positions(account, day, underlyings, bars_by_symbol, contracts_by_symbol, scenario)
        if day.weekday() == 4:
            # Decisions use Friday close; fills begin on the next available bar.
            for available in [p for p in account.positions if p.phase == "assigned_stock" and p.contract == ""]:
                _open_covered_call(account, day, available, bars_by_symbol, contracts_by_symbol, scenario)
            if len(account.positions) < 2 and not any(p.phase == "csp" for p in account.positions):
                _enter_next_week(account, day, underlyings, bars_by_symbol, contracts_by_symbol, scenario, "csp", 2)
        account.events.append({"day": day, "event": "mark", "equity": _mark(account, day, underlyings, bars_by_symbol), "open_positions": len(account.positions)})
    equity = _mark(account, dates[-1], underlyings, bars_by_symbol)
    curve = pd.DataFrame([e for e in account.events if e.get("event") == "mark"])
    if len(curve):
        curve["equity"] = curve["equity"].astype(float)
        drawdown = ((curve["equity"] / curve["equity"].cummax()) - 1.0).min() * 100.0
    else:
        drawdown = 0.0
    trades = pd.DataFrame(account.trades)
    pnl = equity - CAPITAL
    metrics = {
        "return_pct": pnl / CAPITAL * 100.0,
        "pnl_usd": pnl,
        "max_drawdown_pct": drawdown,
        "trade_legs": len(trades),
        "opened_contracts": int((trades.action == "sell").sum()) if len(trades) else 0,
        "closed_contracts": int((trades.action == "buy").sum()) if len(trades) else 0,
        "assigned_puts": account.assigned_count,
        "expired_options": account.expired_count,
        "take_profits": account.tp_count,
        "rolls": account.roll_count,
        "data_gaps": account.data_gaps,
        "ending_equity": equity,
        "buy_hold_return_pct": _buy_hold(underlyings, start, end),
        "events": len(account.events),
        "open_positions_end": len(account.positions),
    }
    return metrics, curve, trades


def main() -> None:
    global UNDERLYINGS
    underlyings, option_bars, contracts_by_symbol = _load_data()
    UNDERLYINGS = underlyings
    bars_by_symbol = {symbol: _option_frame(option_bars, symbol) for symbol in set(option_bars.index.get_level_values(0))}
    rows, curves, trades = [], [], []
    for window, (start, end) in WINDOWS.items():
        for scenario_name, scenario in SCENARIOS.items():
            metrics, curve, trade_df = _run_window(underlyings, bars_by_symbol, contracts_by_symbol, start, end, scenario)
            rows.append({"window": window, "start": start, "end": end, "scenario": scenario_name, **metrics})
            if len(curve):
                curve.insert(0, "window", window)
                curve.insert(1, "scenario", scenario_name)
                curves.append(curve)
            if len(trade_df):
                trade_df.insert(0, "window", window)
                trade_df.insert(1, "scenario", scenario_name)
                trades.append(trade_df)
    result = pd.DataFrame(rows)
    result.to_csv(f"{OUT}_results.csv", index=False)
    pd.concat(curves, ignore_index=True).to_csv(f"{OUT}_equity_curves.csv", index=False)
    pd.concat(trades, ignore_index=True).to_csv(f"{OUT}_trades.csv", index=False) if trades else Path(f"{OUT}_trades.csv").write_text("\n", encoding="utf-8")
    manifest = {"source": "Alpaca historical option OHLC bars + underlying OHLCV; no synthetic bars", "capital": CAPITAL, "commission_per_contract_per_side": COMMISSION, "symbols": sorted(underlyings), "windows": WINDOWS, "scenarios": SCENARIOS, "selection": "nearest available 21-45 DTE contract to target moneyness using underlying close; entry on next option bar open", "assignment": "expiration-based ITM assignment; early assignment is not observed and remains a limitation", "pricing": "short option marked at daily close; missing option bar falls back to intrinsic and increments data_gaps", "delta": "historical delta unavailable; 5%/10% moneyness proxy", "options_quote_limit": "OHLC bars do not expose bid/ask, so percentage slippage is applied", "results_csv": f"{OUT}_results.csv"}
    Path(f"{OUT}_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(result.to_string(index=False))


if __name__ == "__main__":
    main()
