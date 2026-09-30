import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scalperlab.db import Database
from scalperlab.mt5_gateway import MT5Gateway
from scalperlab.sr_quant.historical_time import (
    HistoricalTimeUnverified,
    convert_documented_history,
)
from scalperlab.sr_quant.time_archive import examine_sample


def sample(hour: int, tick: int, offset: int = 10800):
    frames = {}
    for frame, period in (("M1", 60), ("M5", 300), ("M15", 900), ("H1", 3600)):
        utc_open = tick // period * period
        raw_open = utc_open + offset
        def row(raw):
            return {"time": raw, "open": 1.0, "high": 1.2,
                    "low": 0.9, "close": 1.1, "tick_volume": 4,
                    "spread": 2, "real_volume": 0}
        frames[frame] = {"closed": [row(raw_open - period)],
                         "forming": row(raw_open)}
    return {"ok": True, "symbol": "EURUSD#", "terminal_id": "test",
            "account": {"login": "123", "server": "Broker-7"},
            "terminal": {"build": 5400, "data_path": "private"},
            "captured_utc": tick, "frames": frames,
            "tick": {"ok": True, "time": tick,
                     "time_normalization": {"basis": "UTC",
                                            "server_utc_offset_seconds": offset}}}


class SrTimeArchiveTests(unittest.TestCase):
    def test_gateway_raw_sample_is_read_only_and_preserves_timestamps(self):
        hour = 1_700_000_000 // 3600 * 3600
        source = sample(hour, hour + 3590)
        class FakeMT5:
            TIMEFRAME_M1, TIMEFRAME_M5, TIMEFRAME_M15, TIMEFRAME_H1 = 1, 5, 15, 60
            def account_info(self):
                return SimpleNamespace(login=123, server="Broker-7")
            def terminal_info(self):
                return SimpleNamespace(connected=True, data_path="terminal", build=5400)
            def symbol_info(self, name):
                return SimpleNamespace(name=name, visible=True, point=0.00001,
                                       digits=5, volume_min=0.01, volume_step=0.01,
                                       trade_mode=4)
            def copy_rates_from_pos(self, _symbol, timeframe, _start, _count):
                frame = {1: "M1", 5: "M5", 15: "M15", 60: "H1"}[timeframe]
                data = source["frames"][frame]
                return [*data["closed"], data["forming"]]
        gateway = MT5Gateway(FakeMT5(), terminal_id="test")
        with patch.object(gateway, "_connect", return_value=gateway._mt5), \
             patch.object(gateway, "current_tick", return_value=source["tick"]):
            result = gateway.sr_raw_time_sample("EURUSD#", 2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["frames"]["H1"]["forming"]["time"],
                         source["frames"]["H1"]["forming"]["time"])

    def test_forward_bar_requires_forming_then_closed(self):
        hour = 1_700_000_000 // 3600 * 3600
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "archive.sqlite")
            first = db.archive_sr_time_sample(
                account_sha256="a" * 64, sample=sample(hour, hour + 3590),
                save_diagnostic=True)
            self.assertEqual(first["archived_frames"], [])
            second_sample = sample(hour, hour + 3610)
            second = db.archive_sr_time_sample(
                account_sha256="a" * 64, sample=second_sample)
            self.assertEqual(set(second["archived_frames"]), {"M5", "M15", "H1"})
            status = db.sr_time_archive_status(account_sha256="a" * 64,
                                               symbol="EURUSD#")
            self.assertEqual({item["timeframe"]: item["count"]
                              for item in status["bars"]}, {"M5": 1, "M15": 1, "H1": 1})
            self.assertEqual(len(status["diagnostic_samples"]), 1)
            comparison = db.audit_sr_time_sample(account_sha256="a" * 64,
                                                 sample=second_sample)
            self.assertEqual(comparison["H1"]["matched"], 1)
            with db.connect() as connection:
                payload = connection.execute(
                    "SELECT sample_zlib FROM sr_raw_time_samples").fetchone()[0]
            import zlib
            self.assertNotIn(b'"login"', zlib.decompress(payload))
            self.assertNotIn(b'private', zlib.decompress(payload))

    def test_offset_change_does_not_certify_bar(self):
        hour = 1_700_000_000 // 3600 * 3600
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "archive.sqlite")
            db.archive_sr_time_sample(account_sha256="a" * 64,
                                      sample=sample(hour, hour + 3590))
            result = db.archive_sr_time_sample(account_sha256="a" * 64,
                                               sample=sample(hour, hour + 3610, 7200))
            self.assertEqual(result["archived_frames"], [])

    def test_invalid_m1_anchor_fails_closed(self):
        hour = 1_700_000_000 // 3600 * 3600
        data = sample(hour, hour + 3590)
        data["frames"]["M1"]["forming"]["time"] -= 180
        self.assertEqual(examine_sample(data)["code"], "m1_anchor_ambiguous")

    def test_documented_history_rejects_unknown_and_ambiguous_time(self):
        source = "f" * 64
        policy = {"version": "sr-broker-history-v1", "server": "Broker-7",
                  "source_url": "https://broker.example/time", "source_sha256": source,
                  "intervals": [{"start_utc": 0, "end_utc": 100000, "offset_seconds": 7200}],
                  "anchors": [{"source": "independent_utc_evidence",
                               "evidence_url": "https://evidence.example/anchor",
                               "raw_time": 10800, "utc_time": 3600}]}
        rows = [{"time": 10800, "open": 1}, {"time": 14400, "open": 2}]
        converted = convert_documented_history(rows, server="Broker-7", policy=policy)
        self.assertEqual([row["time"] for row in converted], [3600, 7200])
        with self.assertRaises(HistoricalTimeUnverified):
            convert_documented_history(rows, server="Other", policy=policy)
        with self.assertRaises(HistoricalTimeUnverified):
            convert_documented_history([{"time": 200000}], server="Broker-7", policy=policy)
        policy["intervals"].append({"start_utc": 100000, "end_utc": 200000,
                                    "offset_seconds": 10800})
        with self.assertRaises(HistoricalTimeUnverified):
            convert_documented_history(rows, server="Broker-7", policy=policy)

    def test_both_seasonal_boundaries_fail_on_gap_or_duplicate_hour(self):
        intervals = [(0, 100000, 7200), (100000, 200000, 10800),
                     (200000, 300000, 7200)]
        anchors_utc = [99000, 101000, 199000, 201000]
        offsets = [7200, 10800, 10800, 7200]
        policy = {"version": "sr-broker-history-v1", "server": "Broker-7",
                  "source_url": "https://broker.example/time",
                  "source_sha256": "f" * 64,
                  "intervals": [{"start_utc": begin, "end_utc": end,
                                 "offset_seconds": offset}
                                for begin, end, offset in intervals],
                  "anchors": [{"source": "independent_utc_evidence",
                               "evidence_url": "https://evidence.example/anchor",
                               "raw_time": utc + offset, "utc_time": utc}
                              for utc, offset in zip(anchors_utc, offsets, strict=True)]}
        valid = convert_documented_history(
            [{"time": 106200}, {"time": 111800}],
            server="Broker-7", policy=policy)
        self.assertEqual([row["time"] for row in valid], [99000, 101000])
        with self.assertRaises(HistoricalTimeUnverified):
            convert_documented_history([{"time": 108000}],
                                       server="Broker-7", policy=policy)
        with self.assertRaises(HistoricalTimeUnverified):
            convert_documented_history([{"time": 209000}],
                                       server="Broker-7", policy=policy)


if __name__ == "__main__":
    unittest.main()
