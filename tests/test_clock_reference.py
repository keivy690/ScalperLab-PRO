import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scalperlab.clock_monitor import inspect_mt5_clock
from scalperlab.mt5_calendar_bridge import BRIDGE_FILE, read_clock_export
from scalperlab.mt5_gateway import MT5Gateway
from tests.test_mt5_time import FakeRatesMT5


class ClockReferenceTests(unittest.TestCase):
    def test_publishers_are_declared_as_services_not_chart_scripts(self):
        root = Path(__file__).resolve().parents[1] / 'MT5'
        for name in ('ScalperLabClockService', 'ScalperLabCalendarService'):
            source = (root / (name + '.mq5')).read_text(encoding='utf-8')
            self.assertRegex(source, r'(?m)^#property service$')
            self.assertIn('MQL_PROGRAM_TYPE', source)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "Files").mkdir()
        self.now = 1_790_262_589.0
        self.payload = {
            "schema": 1, "account_login": 123, "account_server": "Test-Demo",
            "captured_at_epoch": self.now - 1, "server_utc_offset_seconds": 10800,
            "trade_server_time": datetime.fromtimestamp(self.now - 1 + 10800, timezone.utc).strftime(
                "%Y.%m.%d %H:%M:%S"),
            "status": "unavailable", "events": [],
        }
        self.publish()

    def publish(self):
        (self.root / "Files" / BRIDGE_FILE).write_text(json.dumps(self.payload), encoding="utf-8")

    def read(self):
        return read_clock_export(self.root, login="123", server="Test-Demo", now=self.now)

    def test_clock_does_not_depend_on_economic_calendar_availability(self):
        result = self.read()
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["server_utc_offset_seconds"], 10800)
        self.assertEqual(result["identity_scope"], "account_server")

    def test_dedicated_clock_is_terminal_scoped_and_never_falls_back(self):
        terminal = self.root / 'terminal'
        files = terminal / 'MQL5' / 'Files'
        files.mkdir(parents=True)
        services = terminal / 'MQL5' / 'Services'
        services.mkdir()
        (services / 'ScalperLabClockService.ex5').touch()
        def read():
            return read_clock_export(self.root, login='123', server='Test-Demo',
                                     terminal_data_path=str(terminal), now=self.now)
        self.assertFalse(read()['ok'])  # Fresh legacy calendar cannot hide missing service.
        payload={**self.payload,'schema':2,'provider':'ScalperLabClockService',
                 'version':'2.00','terminal_data_path':str(terminal),'connected':True}
        path=files/'ScalperLab_clock_v2.json'
        path.write_text(json.dumps(payload),encoding='utf-8')
        self.assertTrue(read()['ok'])
        for change in ({'connected':False}, {'version':'unknown'},
                       {'terminal_data_path':str(self.root/'other')},
                       {'account_login':999}, {'captured_at_epoch':self.now-46}):
            with self.subTest(change=change):
                path.write_text(json.dumps({**payload,**change}),encoding='utf-8')
                self.assertFalse(read()['ok'])
        path.write_text('{broken',encoding='utf-8')
        self.assertFalse(read()['ok'])
        path.write_text(json.dumps(payload),encoding='utf-8')
        self.assertTrue(read()['ok'])  # Recovers after valid publication resumes.

    def test_invalid_stale_future_identity_and_nonfinite_snapshots_fail(self):
        original = dict(self.payload)
        for changes in (
            {"account_login": 456}, {"account_server": "Other"},
            {"captured_at_epoch": self.now - 301}, {"captured_at_epoch": self.now + 6},
            {"captured_at_epoch": float("nan")}, {"server_utc_offset_seconds": 999999},
            {"server_utc_offset_seconds": True}, {"server_utc_offset_seconds": 10860},
            {"server_utc_offset_seconds": 7200}, {"trade_server_time": "invalid"},
            {"terminal_data_path": "other-terminal"},
        ):
            with self.subTest(changes=changes):
                self.payload = {**original, **changes}
                self.publish()
                self.assertFalse(self.read()["ok"])

    def test_missing_snapshot_cannot_fall_back_to_tick_inference(self):
        (self.root / "Files" / BRIDGE_FILE).unlink()
        self.assertEqual(self.read()["code"], "clock_unavailable")

    def test_snapshot_offset_refreshes_on_dst_change(self):
        self.payload["server_utc_offset_seconds"] = 7200
        self.payload["trade_server_time"] = datetime.fromtimestamp(
            self.now - 1 + 7200, timezone.utc).strftime("%Y.%m.%d %H:%M:%S")
        self.publish()
        self.assertEqual(self.read()["server_utc_offset_seconds"], 7200)

    def gateway(self, age):
        fake = FakeRatesMT5(self.now, offset_seconds=10800)
        terminal = fake.terminal_info()
        terminal.commondata_path = str(self.root)
        fake.terminal_info = lambda: terminal
        original = fake.symbol_info_tick

        def quote(symbol):
            tick = original(symbol)
            # Generate independently for every call; never mutate the fixture.
            from types import SimpleNamespace
            delta = age if symbol == "FX-CLOSED" else 2
            return SimpleNamespace(bid=tick.bid, ask=tick.ask,
                                   time=tick.time - delta, time_msc=tick.time_msc - delta * 1000)

        fake.symbol_info_tick = quote
        gateway = MT5Gateway(fake)
        self.addCleanup(gateway.shutdown)
        return gateway

    def test_gateway_and_monitor_ignore_closed_market_without_changing_offset(self):
        for age in (900, 10800, 46800, 86400):
            with self.subTest(age=age), patch("time.time", return_value=self.now):
                result = inspect_mt5_clock(self.gateway(age), ["FX-CLOSED", "BTCUSD#"],
                                          terminal_id="test", account_fingerprint="123@Test-Demo")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["symbols"], ["BTCUSD#"])
            old = result["mt5_tick_diagnostics"][0]
            self.assertEqual(old["age_seconds"], age)
            self.assertEqual(old["server_utc_offset_seconds"], 10800)
            self.assertFalse(old["accepted"])

    def test_all_stale_is_quote_unavailability_not_timezone_divergence(self):
        with patch("time.time", return_value=self.now):
            result = inspect_mt5_clock(self.gateway(900), ["FX-CLOSED"],
                                      terminal_id="test", account_fingerprint="123@Test-Demo")
        self.assertFalse(result["ok"])
        self.assertEqual(result["severity"], "transient")
        self.assertIn("Sem cotação recente", result["detail"])

    def test_gateway_rejects_changed_account_and_preserves_reference_error(self):
        self.payload["account_login"] = 456
        self.publish()
        with patch("time.time", return_value=self.now):
            result = self.gateway(900).current_tick("BTCUSD#")
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "clock_identity")


if __name__ == "__main__":
    unittest.main()
