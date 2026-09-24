import unittest
from datetime import datetime, timezone

from scalperlab.strategy_rules import (
    broker_swap_carry,
    cross_sectional_currency_momentum,
    time_series_momentum,
    weekend_gap_reversal,
)


def bars(count=40, start=1.0, step=0.001):
    return [{"time": 1_700_000_000 + i * 86400, "open": start + i * step,
             "high": start + i * step + 0.01, "low": start + i * step - 0.01,
             "close": start + i * step + 0.002} for i in range(count)]


class StrategyRuleTests(unittest.TestCase):
    def test_time_series_momentum_returns_closed_bar_direction_and_stop(self):
        result = time_series_momentum(bars(), 20)
        self.assertEqual(result["phase"], "sinal")
        self.assertEqual(result["side"], "BUY")
        self.assertGreater(result["stop_distance"], 0)

    def test_cross_sectional_selects_direct_strong_weak_pair(self):
        up = bars(start=1.0, step=0.003)
        down = bars(start=1.5, step=-0.002)
        markets = {
            "EURUSD": {"contract": {"currency_base": "EUR", "currency_profit": "USD"}, "bars": up},
            "GBPUSD": {"contract": {"currency_base": "GBP", "currency_profit": "USD"}, "bars": up},
            "USDJPY": {"contract": {"currency_base": "USD", "currency_profit": "JPY"}, "bars": down},
        }
        result = cross_sectional_currency_momentum(markets, 20)
        self.assertEqual(result["phase"], "sinal")
        self.assertEqual((result["symbol"], result["side"]), ("EURUSD", "BUY"))

    def test_swap_carry_blocks_nonpositive_swap(self):
        result = broker_swap_carry({"contract": {"swap_long": -1, "swap_short": 0}, "bars": bars()})
        self.assertEqual(result["phase"], "sem_sinal")

    def test_swap_carry_uses_positive_broker_direction(self):
        result = broker_swap_carry({"contract": {"swap_long": -1, "swap_short": 2}, "bars": bars()})
        self.assertEqual(result["phase"], "sinal")
        self.assertEqual(result["side"], "SELL")

    def test_weekend_gap_only_signals_in_window_and_before_target_touch(self):
        now = datetime(2026, 9, 20, 21, 5, tzinfo=timezone.utc)  # Sunday 17:05 New York (EDT)
        local_open = datetime(2026, 9, 20, 17, 0, tzinfo=__import__("zoneinfo").ZoneInfo("America/New_York"))
        open_epoch = int(local_open.timestamp())
        friday = datetime(2026, 9, 18, 16, 59, tzinfo=__import__("zoneinfo").ZoneInfo("America/New_York"))
        friday_epoch = int(friday.timestamp())
        intraday = [{"time": friday_epoch, "open": 1.0, "high": 1.01, "low": 0.99, "close": 1.0},
                    {"time": open_epoch, "open": 1.2, "high": 1.21, "low": 1.19, "close": 1.2}]
        result = weekend_gap_reversal(intraday, bars(), now=now, timezone_name="America/New_York",
                                      gap_atr_multiple=1.5, reward_risk=1.5)
        self.assertEqual(result["phase"], "sinal")
        self.assertEqual(result["side"], "SELL")
        intraday.append({"time": open_epoch + 60, "open": 1.1, "high": 1.11, "low": 0.99, "close": 1.0})
        result = weekend_gap_reversal(intraday, bars(), now=now, timezone_name="America/New_York",
                                      gap_atr_multiple=1.5, reward_risk=1.5)
        self.assertEqual(result["phase"], "janela_perdida")


if __name__ == "__main__":
    unittest.main()
