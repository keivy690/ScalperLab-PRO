import unittest

from scalperlab.bar_time import normalize_bar_times
from scalperlab.mt5_time import MT5TimeError


class BarTimeTests(unittest.TestCase):
    def convert(self, offset=10800, age=0, period="M2", times=None):
        now = 1790431629
        bars = [{"time": t, "close": 1.2} for t in (times if times is not None else
                [1790431080 + offset, 1790431200 + offset, 1790431320 + offset])]
        return normalize_bar_times(bars, m1_open=1790431620 + offset - age,
                                   tick_utc=now, server_offset=10800, timeframe=period), bars

    def test_server_candles_shift_once_and_preserve_raw_data(self):
        (result, metadata), original = self.convert()
        self.assertEqual(result[-1]["time"], 1790431320)
        self.assertEqual(result[-1]["raw_time"], original[-1]["time"])
        self.assertEqual(metadata["bar_offset_applied_seconds"], 10800)
        self.assertEqual(original[-1]["time"], 1790442120)

    def test_utc_bars_are_unchanged_even_with_server_offset(self):
        (result, metadata), original = self.convert(offset=0)
        self.assertEqual(result, original)
        self.assertEqual(metadata["bar_offset_applied_seconds"], 0)

    def test_stale_forming_bar_cannot_determine_encoding(self):
        with self.assertRaisesRegex(MT5TimeError, "não confirmou"):
            self.convert(age=900)

    def test_ambiguous_malformed_and_dst_discontinuities_are_rejected(self):
        base = 1790442120
        for times in ([base, base], [base, base - 120], [base - 3720, base],
                      [base - 90000, base]):
            with self.subTest(times=times), self.assertRaises(MT5TimeError):
                self.convert(times=times)

    def test_long_timeframes_need_historical_timezone_rule_for_server_bars(self):
        with self.assertRaisesRegex(MT5TimeError, "regra histórica"):
            self.convert(period="D1")

    def test_utc_history_does_not_require_server_offset_history(self):
        (result, metadata), original = self.convert(offset=0, period="D1", times=[1700000000])
        self.assertEqual(result, original)
        self.assertEqual(metadata["bar_offset_applied_seconds"], 0)

    def test_live_series_uses_only_contiguous_tail_and_reports_discarded_bars(self):
        bars = [{"time": t} for t in [1790438400, 1790442000, 1790442120]]
        result, metadata = normalize_bar_times(
            bars, m1_open=1790442420, tick_utc=1790431629, server_offset=10800,
            timeframe="M2", allow_recent_tail=True)
        self.assertEqual(len(result), 2)
        self.assertEqual(metadata["bars_dropped_for_time_validation"], 1)
        self.assertEqual(len(bars), 3)


if __name__ == "__main__":
    unittest.main()
