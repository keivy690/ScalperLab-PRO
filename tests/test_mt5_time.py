import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scalperlab.market_analyst import analyze_market
from scalperlab.mt5_gateway import MT5Gateway
from scalperlab.mt5_time import MT5TimeError, normalize_tick_time


class MT5TimeNormalizationTests(unittest.TestCase):
    def test_normalizes_server_tick_three_hours_ahead(self):
        now = 1_790_262_589.958
        raw_time_msc = int((now + 3 * 60 * 60 + 0.08) * 1000)
        result = normalize_tick_time(raw_time_msc // 1000, raw_time_msc, now_epoch=now)

        self.assertEqual(result.server_utc_offset_seconds, 3 * 60 * 60)
        self.assertEqual(result.utc_time_msc, raw_time_msc - 3 * 60 * 60 * 1000)
        self.assertLessEqual(result.age_seconds, 0.1)
        self.assertGreater(result.age_seconds, -1.0)

    def test_utc_tick_is_not_shifted(self):
        now = 1_790_262_589.0
        result = normalize_tick_time(int(now - 2), int((now - 2) * 1000), now_epoch=now)

        self.assertEqual(result.server_utc_offset_seconds, 0)
        self.assertEqual(result.age_seconds, 2.0)

    def test_offset_is_recalculated_when_server_dst_changes(self):
        now = 1_790_262_589.0
        for offset in (2 * 60 * 60, 3 * 60 * 60):
            with self.subTest(offset=offset):
                result = normalize_tick_time(int(now + offset), int((now + offset) * 1000),
                                             now_epoch=now)
                self.assertEqual(result.server_utc_offset_seconds, offset)

    def test_stale_tick_is_rejected(self):
        now = 1_790_262_589.0
        with self.assertRaisesRegex(MT5TimeError, "desatualizado"):
            normalize_tick_time(int(now - 121), int((now - 121) * 1000), now_epoch=now)

    def test_unexplained_clock_skew_is_rejected(self):
        now = 1_790_262_589.0
        with self.assertRaisesRegex(MT5TimeError, "offset confiável"):
            normalize_tick_time(int(now + 600), int((now + 600) * 1000), now_epoch=now)

    def test_future_raw_candle_is_rejected_before_analysis(self):
        now = 1_790_262_589.0
        bars = [{"time": int(now + 3 * 60 * 60 - (59 - index) * 300),
                 "open": 1.1, "high": 1.101, "low": 1.099, "close": 1.1}
                for index in range(60)]

        result = analyze_market("EURUSD#", "M5", bars, {}, now_epoch=now)

        self.assertEqual(result["decision"]["action"], "AGUARDAR")
        self.assertFalse(result["decision"]["order_eligible"])
        self.assertIn("futuro", result["decision"]["reasons"][0])


class FakeRatesMT5:
    TIMEFRAME_M5 = 5
    TIMEFRAME_D1 = 1440

    def __init__(self, now_epoch, offset_seconds=0, bar_age_seconds=420):
        self.now_epoch = now_epoch
        self.offset_seconds = offset_seconds
        self.bar_age_seconds = bar_age_seconds
        raw_tick_msc = int((now_epoch + offset_seconds) * 1000)
        self.tick = SimpleNamespace(time=raw_tick_msc // 1000, time_msc=raw_tick_msc,
                                    bid=1.1, ask=1.1001)
        raw_bar_time = int(now_epoch - bar_age_seconds + offset_seconds)
        self.rates = [{"time": raw_bar_time, "open": 1.1, "high": 1.101,
                       "low": 1.099, "close": 1.1005, "tick_volume": 10,
                       "spread": 10, "real_volume": 0}]

    def initialize(self, **_kwargs):
        return True

    def shutdown(self):
        return None

    def terminal_info(self):
        return SimpleNamespace(connected=True)

    def symbol_info(self, symbol):
        return SimpleNamespace(name=symbol, visible=True, digits=5, point=0.00001,
                               trade_tick_size=0.00001, trade_tick_value_profit=1.0,
                               trade_tick_value_loss=1.0, trade_contract_size=100000.0,
                               currency_base="EUR", currency_profit="USD", currency_margin="EUR",
                               country="", sector_name="", swap_long=0.0, swap_short=0.0,
                               swap_mode=0, trade_mode=4, volume_min=0.01, volume_max=100.0,
                               volume_step=0.01, trade_stops_level=0, filling_mode=1,
                               trade_exemode=2)

    def symbol_select(self, _symbol, _enabled):
        return True

    def copy_rates_from_pos(self, _symbol, _timeframe, _start, _count):
        return self.rates

    def symbol_info_tick(self, _symbol):
        return self.tick


class MT5GatewayTimeNormalizationTests(unittest.TestCase):
    def test_market_rates_and_ticks_are_normalized_to_utc(self):
        now = 1_790_262_589.958
        fake = FakeRatesMT5(now, offset_seconds=3 * 60 * 60)
        gateway = MT5Gateway(fake)
        try:
            with patch("scalperlab.mt5_time.time.time", return_value=now), \
                    patch("scalperlab.mt5_gateway.time.time", return_value=now):
                market = gateway.strategy_market_data("EURUSD#", count=1, timeframe="M5")
                tick = gateway.current_tick("EURUSD#")
        finally:
            gateway.shutdown()

        self.assertTrue(market["ok"], market)
        self.assertEqual(market["bars"][0]["time"], fake.rates[0]["time"] - 3 * 60 * 60)
        self.assertEqual(market["time_normalization"]["server_utc_offset_seconds"], 3 * 60 * 60)
        self.assertTrue(tick["ok"], tick)
        self.assertEqual(tick["time"], fake.tick.time - 3 * 60 * 60)
        self.assertEqual(tick["time_normalization"]["basis"], "UTC")

    def test_stale_market_bars_are_rejected_even_with_a_fresh_tick(self):
        now = 1_790_262_589.0
        gateway = MT5Gateway(FakeRatesMT5(now, offset_seconds=3 * 60 * 60,
                                         bar_age_seconds=3600))
        try:
            with patch("scalperlab.mt5_time.time.time", return_value=now), \
                    patch("scalperlab.mt5_gateway.time.time", return_value=now):
                market = gateway.strategy_market_data("EURUSD#", count=1, timeframe="M5")
        finally:
            gateway.shutdown()

        self.assertFalse(market["ok"])
        self.assertIn("desatualizado", market["detail"])

    def test_daily_history_remains_usable_after_a_weekend_or_short_holiday(self):
        now = 1_790_262_589.0
        gateway = MT5Gateway(FakeRatesMT5(now, offset_seconds=3 * 60 * 60,
                                         bar_age_seconds=3 * 86_400))
        try:
            with patch("scalperlab.mt5_time.time.time", return_value=now), \
                    patch("scalperlab.mt5_gateway.time.time", return_value=now):
                market = gateway.strategy_market_data("EURUSD#", count=1, timeframe="D1")
        finally:
            gateway.shutdown()

        self.assertTrue(market["ok"], market)


if __name__ == "__main__":
    unittest.main()
