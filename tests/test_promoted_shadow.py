import unittest

import pandas as pd

from bot import build_strategies
from strategies.promoted_shadow import (
    PromotedBreakout20_55,
    PromotedTrendPullback,
    _is_fresh_confirmation,
)


class PromotedShadowTests(unittest.TestCase):
    def setUp(self):
        self.frame = pd.DataFrame(
            {
                "open": [10.0, 10.1],
                "high": [10.2, 10.4],
                "low": [9.8, 10.0],
                "close": [10.1, 10.3],
                "volume": [1000, 1200],
            },
            index=pd.date_range("2026-08-21 14:00", periods=2, freq="15min", tz="UTC"),
        )

    def test_build_strategies_registers_promoted_long_adapters(self):
        cfg = {
            "strategies": {
                "day_momentum": {"enabled": False},
                "day_breakout": {"enabled": False},
                "swing_trend": {"enabled": False},
            },
            "universo": {"options_reto": {"direction": "bull"}},
            "promoted_layers": {
                "enabled": True,
                "trend_pullback": True,
                "breakout_20_55": True,
            },
            "trend_pullback_shadow": {"timeframe": "15min"},
            "breakout_20_55_shadow": {"timeframe": "15min"},
        }
        strategies = build_strategies(cfg, object())
        self.assertEqual(
            set(strategies),
            {"opt_promoted_trend_pullback", "opt_promoted_breakout_20_55"},
        )

    def test_fresh_confirmation_requires_last_closed_bar(self):
        observation = {"confirmation_timestamp": self.frame.index[-1].isoformat()}
        stale = {"confirmation_timestamp": self.frame.index[-2].isoformat()}
        self.assertTrue(_is_fresh_confirmation(observation, self.frame))
        self.assertFalse(_is_fresh_confirmation(stale, self.frame))

    def test_trend_pullback_returns_none_on_stale_detector_result(self):
        strategy = PromotedTrendPullback({"timeframe": "15min"})
        strategy._evaluate = lambda _df, _symbol: {
            "status": "confirmed",
            "direction": "bull",
            "confirmation_timestamp": self.frame.index[-2].isoformat(),
            "stop_price": 9.0,
            "target_price": 12.0,
        }
        signal = strategy.scan(self.frame, symbol="TQQQ")
        self.assertFalse(signal.tradable)
        self.assertEqual(signal.reason, "stale_confirmation")

    def test_breakout_maps_fresh_bull_confirmation_to_long_signal(self):
        strategy = PromotedBreakout20_55({"timeframe": "15min"})
        strategy._evaluate = lambda _df, _symbol: {
            "status": "confirmed",
            "direction": "bull",
            "confirmation_timestamp": self.frame.index[-1].isoformat(),
            "stop_price": 9.0,
            "target_price": 12.0,
        }
        signal = strategy.scan(self.frame, symbol="TQQQ")
        self.assertTrue(signal.tradable)
        self.assertEqual(signal.signal_type.value, "long")
        self.assertEqual(signal.stop_price, 9.0)
        self.assertEqual(signal.target_price, 12.0)


if __name__ == "__main__":
    unittest.main()
