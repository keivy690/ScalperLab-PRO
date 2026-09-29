import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scalperlab.db import Database
from scalperlab.sr_quant.core import evaluate_bundle, read_live_bundle
from scalperlab.sr_quant.replay import run_sr_replay
from scalperlab.sr_quant.service import SrResearchService


def bars(start, seconds, count, slope=0.00001):
    rows = []
    for index in range(count):
        close = 1.1 + index * slope
        rows.append({"time": start + index * seconds, "open": close - slope / 2,
                     "high": close + 0.0002, "low": close - 0.0002,
                     "close": close, "spread": 2})
    return rows


class SrQuantTests(unittest.TestCase):
    def setUp(self):
        self.decision_time = 1_700_000_000
        self.bundle = {"symbol": "EURUSD#", "contract": {"point": 0.00001},
                       "tick": {"bid": 1.103, "ask": 1.10302},
                       "frames": {
                           "H1": bars(self.decision_time - 260 * 3600, 3600, 260),
                           "M15": bars(self.decision_time - 260 * 900, 900, 260),
                           "M5": bars(self.decision_time - 300 * 300, 300, 300),
                       }}

    def test_future_bars_cannot_change_past_decision(self):
        original = evaluate_bundle(self.bundle, decision_time=self.decision_time)
        augmented = copy.deepcopy(self.bundle)
        for frame, seconds in (("H1", 3600), ("M15", 900), ("M5", 300)):
            augmented["frames"][frame].append({
                **augmented["frames"][frame][-1], "time": self.decision_time + seconds,
                "close": 9.0, "high": 9.1, "low": 8.9, "open": 9.0})
        future_ignored = evaluate_bundle(augmented, decision_time=self.decision_time)
        self.assertEqual(original, future_ignored)
        self.assertFalse(original["order_eligible"])

    def test_missing_timeframe_fails_closed(self):
        self.bundle["frames"]["H1"] = []
        result = evaluate_bundle(self.bundle, decision_time=self.decision_time)
        self.assertEqual(result["status"], "DADOS_INSUFICIENTES")
        self.assertFalse(result["candidates"])

    def test_live_read_rejects_unverified_historical_timezone(self):
        port = MagicMock()
        port.strategy_market_data.return_value = {
            "ok": True, "symbol": "EURUSD#", "bars": [],
            "time_normalization": {"basis": "UTC", "historical_timezone_verified": False}}
        result = read_live_bundle(port, "EURUSD#")
        self.assertFalse(result["ok"])
        self.assertIn("UTC", result["detail"])
        port.current_tick.assert_not_called()

    def test_h1_m15_cache_expires_at_next_close(self):
        port = MagicMock()
        port.strategy_market_data.side_effect = lambda symbol, count, timeframe: {
            "ok": True, "symbol": symbol, "bars": self.bundle["frames"][timeframe],
            "contract": self.bundle["contract"],
            "time_normalization": {"basis": "UTC", "historical_timezone_verified": True}}
        port.current_tick.return_value = {"ok": True, "bid": 1.103, "ask": 1.10302}
        cache = {}
        with patch("scalperlab.sr_quant.core.time.time", return_value=self.decision_time):
            first = read_live_bundle(port, "EURUSD#", frame_cache=cache)
            second = read_live_bundle(port, "EURUSD#", frame_cache=cache)
        self.assertTrue(first["ok"] and second["ok"])
        self.assertEqual(first["connector_diagnostics"]["calls"], 4)
        self.assertEqual(second["connector_diagnostics"]["calls"], 2)
        self.assertEqual(second["connector_diagnostics"]["frames_cached"], 2)

    def test_evaluation_is_idempotent_per_account_symbol_version_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "sr.sqlite3")
            result = evaluate_bundle(self.bundle, decision_time=self.decision_time)
            database.save_sr_evaluation(account_sha256="a" * 64, result=result)
            changed = {**result, "status": "TAMPERED"}
            database.save_sr_evaluation(account_sha256="a" * 64, result=changed)
            rows = database.list_sr_evaluations()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "EVALUATED")

    def test_service_rejects_duplicate_selection_without_order_capability(self):
        port = MagicMock()
        database = MagicMock()
        service = SrResearchService(database, port)
        result = service.start(["EURUSD#", "EURUSD#"])
        self.assertFalse(result["ok"])
        port.send_demo_analyst_order.assert_not_called()

    def test_multiframe_replay_is_read_only_and_reproducible(self):
        end = self.decision_time
        frames = {"H1": bars(end - 480 * 3600, 3600, 480),
                  "M15": bars(end - 850 * 900, 900, 850),
                  "M5": bars(end - 650 * 300, 300, 650)}
        contract = {"point": 0.00001, "trade_tick_size": 0.00001,
                    "trade_tick_value_profit": 1.0, "trade_tick_value_loss": 1.0,
                    "volume_min": 0.01, "volume_step": 0.01, "chart_mode": 0}
        inputs = dict(symbol="EURUSD#", frames=frames, contract=contract,
                      slippage_points=1, commission_per_lot_round_turn=0,
                      swap_long_per_lot_per_utc_rollover=0,
                      swap_short_per_lot_per_utc_rollover=0, costs_confirmed=True)
        first = run_sr_replay(**inputs)
        second = run_sr_replay(**inputs)
        self.assertEqual(first, second)
        self.assertFalse(first["order_eligible"])
        self.assertGreater(first["segments"]["holdout"]["evaluated_bars"], 0)
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "sr.sqlite3")
            database.save_sr_replay_run(
                run_id="fixed-run", terminal_id="fake", account_sha256="a" * 64,
                symbol="EURUSD#", result=first,
                dataset={"frames": frames, "contract": contract})
            saved = database.get_sr_replay_run("fixed-run")
            self.assertEqual(saved["data_sha256"], first["data_sha256"])
            self.assertEqual(saved["dataset"]["frames"], frames)


if __name__ == "__main__":
    unittest.main()
