import sys
import unittest
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot import _manage_open_position
from options.chains import Leg, OptionContract, OptionStructure, OptionType, SpreadBuilder


class _FakeMarketDataFeed:
    """Solo expone history(), como el MarketDataFeed real. No tiene
    snapshots(): si _manage_open_position lo llamara sobre este objeto
    (el bug original), fallaría con AttributeError."""

    def history(self, symbols, timeframe, days):
        df = pd.DataFrame({"close": [90.0, 91.5]})
        return {symbols[0]: df}


class _FakeOptionFeed:
    """Doble de OptionFeed: expone snapshots() y rellena precios, igual que
    el OptionFeed real (Alpaca) o el simulado."""

    def snapshots(self, contracts, spot=None):
        for c in contracts:
            c.last = 3.0 if c.strike == 85.0 else 1.0
        return contracts


class _FakeBuilder(SpreadBuilder):
    def __init__(self):
        super().__init__(_FakeOptionFeed())

    def vertical_spread_from(self, pos):
        long_c = OptionContract("TQQQ260918C00085000", "TQQQ", OptionType.CALL,
                                 85.0, date(2026, 9, 18))
        short_c = OptionContract("TQQQ260918C00100000", "TQQQ", OptionType.CALL,
                                  100.0, date(2026, 9, 18))
        return OptionStructure(
            "call_spread_TQQQ_85.0_100.0",
            [Leg(long_c, +1), Leg(short_c, -1)], "TQQQ")


class TestManageOpenPosition(unittest.TestCase):
    def test_uses_option_feed_not_market_data_feed_for_snapshots(self):
        """Regresión: _manage_open_position llamaba feed.snapshots() sobre
        el MarketDataFeed (solo tiene history()), no sobre builder.feed
        (OptionFeed). Nunca se ejecutaba en producción porque el estado
        interno de posiciones siempre estaba vacío (ver reconciliación);
        al arreglar eso, el bug quedó expuesto en el primer tick real."""
        feed = _FakeMarketDataFeed()  # sin snapshots() -> el bug lanzaría AttributeError
        builder = _FakeBuilder()
        pos = {"symbol": "TQQQ", "strategy": "reconciled_broker",
               "structure": "call_spread_TQQQ_85.0_100.0",
               "net_premium": 1.97, "max_risk": 197.0}

        sig_type, reason = _manage_open_position(feed, builder, None, pos)

        # No debe lanzar AttributeError; el resultado depende de evaluate_exit,
        # lo relevante aqui es que la llamada completa sin reventar.
        self.assertIn(sig_type, (None, "EXIT"))


if __name__ == "__main__":
    unittest.main()
