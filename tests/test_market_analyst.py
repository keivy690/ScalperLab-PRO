import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scalperlab.db import Database
from scalperlab.market_analyst import MarketAnalystEngine
from scalperlab.mt5_gateway import MT5Gateway


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1

    def initialize(self, **_kwargs):
        return True

    def last_error(self):
        return (0, "ok")

    def account_info(self):
        return SimpleNamespace(login=42, server="Demo", company="Broker", currency="USD",
                               balance=1000.0, equity=1000.0, profit=0.0, trade_mode=0,
                               leverage=100)

    def terminal_info(self):
        return SimpleNamespace(connected=True, name="MetaTrader 5", build=1, trade_allowed=True)

    def symbols_get(self):
        return [SimpleNamespace(name="EURUSD#", visible=True)]


class MarketAnalystSymbolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "test.sqlite3")
        self.gateway = MT5Gateway(FakeMT5())
        self.engine = MarketAnalystEngine(self.db, self.gateway)

    def tearDown(self):
        self.engine.stop()
        self.gateway.shutdown()
        self.temp.cleanup()

    def test_start_rejects_unknown_symbol_and_suggests_broker_name(self):
        self.engine.config["symbols"] = ["EURUSD"]
        result = self.engine.start("observacao")
        self.assertFalse(result["ok"])
        self.assertIn("EURUSD#", result["detail"])
        self.assertFalse(self.engine.state["running"])

    def test_start_accepts_exact_market_watch_symbol(self):
        self.engine.config["symbols"] = ["EURUSD#"]
        result = self.engine.start("observacao")
        self.assertTrue(result["ok"], result)
        self.assertTrue(self.engine.state["running"])

    def test_profile_accepts_broker_suffix_hash(self):
        result = self.engine.configure({"symbols": "GOLD#", "timeframe": "M15"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.engine.config["symbols"], ["GOLD#"])

    def test_profile_preserves_broker_symbol_case(self):
        result = self.engine.configure({"symbols": "HK50Cash#", "timeframe": "M15"})
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.engine.config["symbols"], ["HK50Cash#"])


if __name__ == "__main__":
    unittest.main()
