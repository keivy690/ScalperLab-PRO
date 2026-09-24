import tempfile
import unittest
from pathlib import Path

from scalperlab.db import Database
from scalperlab.execution_engine import ExecutionEngine
from scalperlab.strategy_rules import STRATEGY_TYPES


class FakeGateway:
    strategy_engine_armed = False

    def disarm_order_engine(self, _engine):
        self.strategy_engine_armed = False

    def state(self):
        return {"connected": False, "account": None, "terminal": None}


class ExecutionEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "engine.sqlite3")
        self.engine = ExecutionEngine(self.db, FakeGateway())

    def tearDown(self):
        self.temp.cleanup()

    def test_all_five_approved_adapters_accept_a_valid_profile(self):
        strategies = [{"id": index, "name": name, "status": "approved", "source_type": "description"}
                      for index, name in enumerate(STRATEGY_TYPES, start=1)]
        for strategy in strategies:
            profile = {"strategy_id": strategy["id"], "symbol": "EURUSD", "timezone": "Europe/London",
                       "session_open": "08:00", "trade_end": "11:00", "range_minutes": 15,
                       "lookback_days": 20, "gap_atr_multiple": 1.5, "risk_per_trade_pct": 0.1,
                       "daily_loss_limit_pct": 0.5, "reward_risk": 1.5}
            if strategy["name"] == "Momentum cross-sectional de moedas (literatura)":
                profile["symbols"] = "EURUSD,GBPUSD,USDJPY"
            if strategy["name"] == "Reversão de gap de fim de semana em FX":
                profile["timezone"] = "America/New_York"
            result = self.engine.configure(profile, strategies)
            self.assertTrue(result["ok"], f"{strategy['name']}: {result}")
            self.assertEqual(self.engine.config["strategy_name"], strategy["name"])

    def test_motor_never_arms_order_sending_for_observation_mode(self):
        name = "Momentum de séries temporais em futuros (literatura)"
        strategy = {"id": 1, "name": name, "status": "approved", "source_type": "description"}
        result = self.engine.configure({"strategy_id": 1, "symbol": "EURUSD", "timezone": "Europe/London",
                                       "risk_per_trade_pct": 0.1, "daily_loss_limit_pct": 0.5,
                                       "reward_risk": 1.5}, [strategy])
        self.assertTrue(result["ok"])
        started = self.engine.start("observacao", "", [strategy])
        self.assertFalse(started["ok"])
        self.assertFalse(self.engine.gateway.strategy_engine_armed)

    def test_broker_symbol_suffix_hash_is_accepted(self):
        name = "Momentum de séries temporais em futuros (literatura)"
        strategy = {"id": 1, "name": name, "status": "approved", "source_type": "description"}
        result = self.engine.configure({"strategy_id": 1, "symbol": "GOLD#", "timezone": "Europe/London",
                                        "risk_per_trade_pct": 0.1, "daily_loss_limit_pct": 0.5,
                                        "reward_risk": 1.5}, [strategy])
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.engine.config["symbol"], "GOLD#")


if __name__ == "__main__":
    unittest.main()
