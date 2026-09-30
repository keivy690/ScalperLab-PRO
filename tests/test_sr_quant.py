import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from scalperlab.connectors.audit import AuditedTradingPort
from scalperlab.db import Database
from scalperlab.sr_quant.core import (evaluate_bundle, evaluate_live_broker_bundle,
                                      read_live_broker_bundle, read_live_bundle)
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

    def test_data_quality_block_is_persisted_once_per_bucket(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "sr.sqlite3")
            for _ in range(2):
                database.save_sr_data_event(
                    account_sha256="a" * 64, symbol="EURUSD#",
                    code="historical_timezone_required",
                    detail="Histórico do broker sem regra histórica UTC.")
            rows = database.list_sr_data_events()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["symbol"], "EURUSD#")

    def test_service_rejects_duplicate_selection_without_order_capability(self):
        port = MagicMock()
        database = MagicMock()
        service = SrResearchService(database, port)
        result = service.start(["EURUSD#", "EURUSD#"])
        self.assertFalse(result["ok"])
        port.send_demo_analyst_order.assert_not_called()

    def test_live_broker_time_evaluates_without_claiming_historical_utc(self):
        offset = 10800
        tick_time = self.decision_time
        raw_frames = {}
        for frame, seconds in (("H1", 3600), ("M15", 900), ("M5", 300)):
            closed = bars(tick_time // seconds * seconds - 300 * seconds + offset,
                          seconds, 300)
            raw_frames[frame] = {"closed": closed,
                                 "forming": {**closed[-1], "time": closed[-1]["time"] + seconds}}
        raw_frames["M1"] = {"closed": [], "forming": {
            "time": tick_time // 60 * 60 + offset}}
        port = MagicMock()
        port.sr_raw_time_sample.return_value = {
            "ok": True, "symbol": "EURUSD#", "terminal_id": "test",
            "account": {"login": "123", "server": "Broker-7"},
            "tick": {"ok": True, "time": tick_time, "bid": 1.103,
                     "ask": 1.10302,
                     "time_normalization": {"basis": "UTC",
                                            "server_utc_offset_seconds": offset}},
            "frames": raw_frames}
        with patch("scalperlab.sr_quant.core.examine_sample", return_value={
                "ok": True, "bar_offset_seconds": offset, "sample_sha256": "a" * 64}):
            bundle = read_live_broker_bundle(port, "EURUSD#")
        self.assertTrue(bundle["ok"])
        result = evaluate_live_broker_bundle(bundle)
        self.assertEqual(result["status"], "EVALUATED")
        self.assertEqual(result["decision_time_utc"], tick_time)
        self.assertEqual(result["frame_last_closed"]["M5"],
                         raw_frames["M5"]["closed"][-1]["time"] - offset)
        self.assertFalse(result["historical_timezone_verified"])

    def test_demo_requires_exact_confirmation_and_demo_account(self):
        port = MagicMock(terminal_id="test")
        port.state.return_value = {
            "connected": True, "terminal": {"trade_allowed": True},
            "account": {"login": "123", "server": "Broker-7",
                        "mode": "REAL", "trade_allowed": True,
                        "trade_expert": True}}
        port.validate_market_symbols.return_value = {
            "available": True, "valid": True}
        service = SrResearchService(MagicMock(), port,
                                    clock_service=MagicMock(),
                                    risk_settings=MagicMock())
        self.assertFalse(service.start(["EURUSD#"], "demo", "wrong")["ok"])
        self.assertFalse(service.start(
            ["EURUSD#"], "demo", "INICIAR S/R SOMENTE DEMO")["ok"])
        port.arm_order_engine.assert_not_called()

    def test_demo_signal_is_reserved_once_and_uses_shared_order_port(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "sr.sqlite3")
            port = MagicMock(terminal_id="test")
            port.state.return_value = {
                "connected": True, "terminal": {"trade_allowed": True},
                "account": {"login": "123", "server": "Broker-7",
                            "mode": "DEMO", "trade_allowed": True,
                            "trade_expert": True, "equity": 10000}}
            port.risk_volume.return_value = {"ok": True, "volume": 0.01}
            port.send_demo_sr_order.return_value = {
                "ok": True, "reconciled": True, "ticket": 12345,
                "detail": "Posição DEMO confirmada."}
            clock = MagicMock()
            clock.is_currently_verified.return_value = True
            risk = MagicMock()
            risk.daily_check.return_value = {"ok": True, "remaining_cash": 100}
            risk.profile.return_value = {"max_volume": 0.01}
            risk.budget.return_value = 10
            service = SrResearchService(database, port, clock_service=clock,
                                        risk_settings=risk)
            service._state.update(running=True, mode="demo")
            service._account_sha256 = "a" * 64
            service._account_fingerprint = "123@Broker-7"
            signal = {"strategy": "trend_pullback", "side": "BUY",
                      "status": "CANDIDATE_RESEARCH_ONLY", "stop": 1.09,
                      "signal_bar_open_utc": self.decision_time - 300}
            bundle = {"tick": {"time": self.decision_time, "ask": 1.10,
                               "bid": 1.09998}}
            result = {"candidates": [signal], "atr14_m5": 0.001}
            with patch("scalperlab.sr_quant.service.time.time",
                       return_value=self.decision_time):
                service._maybe_execute("EURUSD#", result, bundle)
                self.assertEqual(result["execution_status"], "CONFIRMADA_MT5")
                service._maybe_execute("EURUSD#", result, bundle)
            self.assertEqual(result["execution_status"], "SINAL_JA_PROCESSADO")
            port.send_demo_sr_order.assert_called_once()

    def test_audited_sr_order_rechecks_budget_without_changing_spread(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Database(Path(directory) / "sr.sqlite3")
            connector = MagicMock(terminal_id="test")
            connector.state.return_value = {"connected": True, "account": {
                "login": "123", "server": "Broker-7", "mode": "DEMO"}}
            connector.send_demo_sr_order.return_value = {
                "ok": True, "reconciled": True, "ticket": 12345,
                "detail": "Posição DEMO confirmada."}
            port = AuditedTradingPort(connector, database)
            risk = MagicMock()
            risk.daily_check.return_value = {"ok": True, "remaining_cash": 5}
            risk.profile.return_value = {"max_volume": 0.01, "version": 1}
            risk.budget.return_value = 10
            port.risk_settings = risk
            response = port.send_demo_sr_order(
                "EURUSD#", "BUY", 0.01, 1.09, 1.12,
                "123@Broker-7", 9, 0.00008, 1.5,
                risk_policy=risk.profile.return_value)
            self.assertTrue(response["ok"])
            passed = connector.send_demo_sr_order.call_args.args
            self.assertEqual(passed[6], 5)
            self.assertEqual(passed[7], 0.00008)

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
