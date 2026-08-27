import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot  # noqa: E402
from options.chains import Leg, OptionContract, OptionStructure, OptionType  # noqa: E402


def _cfg():
    return {
        "risk": {"max_open_positions": 1, "max_risk_per_trade_pct": 5.0},
        "execution": {"order_type": "limit", "limit_offset_pct": 0.0,
                      "default_time_in_force": "day"},
        "universo": {
            "regime_aware": {"enabled": True, "bull_enabled": True,
                             "min_bull_symbols": 1, "max_premium_net": 12.0},
            "relative_strength": {
                "enabled": True, "horizon_bars": 2,
                "top_percentile": 0.75, "bottom_percentile": 0.25,
                "only_positive": True, "allow_shorts": True,
                "min_excess_return": 0.0,
            },
        },
    }


def _frame(values):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="D", tz="UTC")
    return pd.DataFrame({"close": values}, index=idx)


def _structure(net=40.0):
    exp = date.today() + timedelta(days=21)
    long = OptionContract("TESTLONG", "TEST", OptionType.CALL, 100.0, exp,
                          bid=0.75, ask=0.85, last=0.80)
    short = OptionContract("TESTSHORT", "TEST", OptionType.CALL, 105.0, exp,
                           bid=0.35, ask=0.45, last=0.40)
    return OptionStructure("call_spread_TEST_100_105",
                           [Leg(long, 1), Leg(short, -1)], "TEST",
                           max_risk=net, max_profit=100.0 - net)


class _Builder:
    def __init__(self, structure):
        self.structure = structure

    def vertical_spread(self, *args, **kwargs):
        return self.structure


class _Executor:
    dry_run = True

    def __init__(self):
        self.calls = []

    def submit_spread(self, specs, **kwargs):
        self.calls.append((specs, kwargs))
        return {"id": "dry-run-order"}


def test_regime_aware_selects_highest_rsi_bull_symbol():
    regime = {
        "regime": "bull", "bull_count": 3,
        "ticker_status": {
            "AAA": {"bull": True, "rsi": 61.0},
            "BBB": {"bull": True, "rsi": 72.0},
            "CCC": {"bull": False, "rsi": 80.0},
        },
    }
    got = bot._regime_aware_candidates(regime, {"positions": []}, _cfg())
    assert [item["symbol"] for item in got] == ["BBB", "AAA"]
    assert all(item["direction"] == "bull" for item in got)


def test_relative_strength_generates_bull_and_bear_orders_by_global_regime():
    frames = {
        "AAA": _frame([100.0, 100.0, 120.0]),
        "BBB": _frame([100.0, 100.0, 100.0]),
        "CCC": _frame([100.0, 100.0, 80.0]),
        "DDD": _frame([100.0, 100.0, 90.0]),
    }
    cfg = _cfg()
    bull = bot._relative_strength_candidates(
        frames, {"regime": "bull"}, {"positions": []}, cfg)
    bear = bot._relative_strength_candidates(
        frames, {"regime": "bear"}, {"positions": []}, cfg)
    assert [item["symbol"] for item in bull] == ["AAA"]
    assert bull[0]["direction"] == "bull"
    assert [item["symbol"] for item in bear] == ["CCC"]
    assert bear[0]["direction"] == "bear"


def test_managed_entry_rejects_premium_above_cap_before_submit():
    executor = _Executor()
    state = {"positions": [], "entry_intents": {}, "decisions": []}
    rm = SimpleNamespace(approve_option_structure=lambda *args, **kwargs:
                         SimpleNamespace(decision="APPROVED"))
    with patch.object(bot, "save_state"), patch.object(bot, "notify_position_open"):
        result = bot._submit_managed_option_entry(
            executor, _Builder(_structure()), rm, state, _cfg(), 100000.0,
            "TEST", "relative_strength", "bull", 10, 45, 0.25, 0.10,
            30.0, {"regime": "bull"})
    assert result["submitted"] is False
    assert result["reason"].startswith("premium_over_cap:")
    assert executor.calls == []
    assert state["positions"] == []


def test_managed_entry_submits_one_mleg_and_records_call_position():
    executor = _Executor()
    state = {"positions": [], "entry_intents": {}, "decisions": []}
    rm = SimpleNamespace(approve_option_structure=lambda *args, **kwargs:
                         SimpleNamespace(decision="APPROVED"))
    with patch.object(bot, "save_state"), patch.object(bot, "notify_position_open"):
        result = bot._submit_managed_option_entry(
            executor, _Builder(_structure()), rm, state, _cfg(), 100000.0,
            "TEST", "regime_aware", "bull", 10, 45, 0.25, 0.10,
            50.0, {"regime": "bull"})
    assert result["submitted"] is True
    assert len(executor.calls) == 1
    assert len(executor.calls[0][0]) == 2
    assert len(state["positions"]) == 1
    assert state["positions"][0]["kind"] == "call"
    assert state["_broker_reconciliation_halt"] is True
