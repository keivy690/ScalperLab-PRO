import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scalperlab.db import Database
from scalperlab.mt5_gateway import MT5Gateway
from scalperlab.replay import run_pullback_replay
from scalperlab.web import create_app


class FakeMT5:
    ACCOUNT_TRADE_MODE_DEMO = 0
    ACCOUNT_TRADE_MODE_CONTEST = 1
    def initialize(self): return False
    def last_error(self): return (1, "not connected")


class WebTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = Database(Path(self.temp.name) / "test.sqlite3")
        self.app = create_app(database=db, mt5=MT5Gateway(FakeMT5()), token="test-token")
        self.app.config.update(TESTING=True, APP_HOST="127.0.0.1:5000", APP_ORIGIN="http://127.0.0.1:5000")
        self.client = self.app.test_client()
        self.headers = {"X-ScalperLab-Token": "test-token", "Origin": "http://127.0.0.1:5000",
                        "Host": "127.0.0.1:5000"}

    def tearDown(self): self.temp.cleanup()

    def test_api_requires_session_token(self):
        self.assertEqual(self.client.get("/api/state").status_code, 403)

    def test_clock_preflight_uses_read_only_path_and_never_repairs(self):
        clock = self.app.extensions["scalper_system_clock"]
        with patch.object(clock, "verify_read_only", return_value={
                "status": "error", "detail": "Fonte UTC indisponível."}) as read_only, \
             patch.object(clock, "verify_and_synchronize") as repair:
            response = self.client.post("/api/system/clock/synchronize",
                                        headers=self.headers, json={"read_only": True})
        self.assertEqual(response.status_code, 409)
        read_only.assert_called_once_with()
        repair.assert_not_called()

    def test_wrong_host_and_origin_are_rejected(self):
        headers = {**self.headers, "Host": "attacker.example"}
        self.assertEqual(self.client.get("/api/state", headers=headers).status_code, 403)
        headers = {**self.headers, "Origin": "https://attacker.example"}
        self.assertEqual(self.client.get("/api/state", headers=headers).status_code, 403)

    def test_strategy_review_does_not_expose_a_generic_order_endpoint(self):
        response = self.client.post("/api/strategies", headers=self.headers, json={
            "name": "Rompimento", "description": "Entrar no fechamento acima da máxima."
        })
        self.assertEqual(response.status_code, 201)
        strategy_id = response.json["item"]["id"]
        review = self.client.put(f"/api/strategies/{strategy_id}/review", headers=self.headers,
                                 json={"status": "review"})
        self.assertEqual(review.status_code, 200)
        approve = self.client.put(f"/api/strategies/{strategy_id}/review", headers=self.headers,
                                  json={"status": "approved"})
        self.assertEqual(approve.status_code, 200)
        self.assertIn("não inicia", approve.json["note"])
        direct_order = self.client.post(
            "/api/trading/real", headers=self.headers, json={"order": "anything"}
        )
        self.assertEqual(direct_order.status_code, 404)

    def test_trade_audit_routes_require_session_and_return_empty_ledger(self):
        self.assertEqual(self.client.get("/api/trading/audit").status_code, 403)
        audit = self.client.get("/api/trading/audit", headers=self.headers)
        self.assertEqual(audit.status_code, 200)
        self.assertEqual(audit.json["items"], [])
        reconcile = self.client.post("/api/trading/audit/reconcile", headers=self.headers, json={})
        self.assertEqual(reconcile.status_code, 200)
        self.assertEqual(reconcile.json["items"], [])

    def test_replay_routes_are_authenticated_and_keep_runs_local(self):
        self.assertEqual(self.client.get("/api/analyst/replays").status_code, 403)
        response = self.client.get("/api/analyst/replays", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])

    def test_sr_research_routes_require_token_and_start_only_when_motors_stopped(self):
        page = self.client.get("/", headers=self.headers)
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="sr-symbol-1"', page.data)
        self.assertIn(b'id="sr-replay-form"', page.data)
        self.assertEqual(self.client.get("/api/sr-quant/evaluations").status_code, 403)
        response = self.client.get("/api/sr-quant/evaluations", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["items"], [])
        analyst = self.app.extensions["scalper_analyst"]
        service = self.app.extensions["scalper_sr_research"]
        with patch.object(analyst, "snapshot", return_value={"state": {"running": True}}), \
             patch.object(service, "start") as start:
            blocked = self.client.post("/api/sr-quant/start", headers=self.headers,
                                       json={"symbols": ["EURUSD#"]})
        self.assertEqual(blocked.status_code, 409)
        start.assert_not_called()

    def test_sr_replay_does_not_consult_mt5_when_research_active(self):
        service = self.app.extensions["scalper_sr_research"]
        port = self.app.extensions["scalper_mt5"]
        with patch.object(service, "snapshot", return_value={"running": True, "busy": True}), \
             patch.object(port, "historical_market_data") as history:
            response = self.client.post("/api/sr-quant/replay", headers=self.headers,
                                        json={"symbol": "EURUSD#", "bars": 600,
                                              "costs_confirmed": True})
        self.assertEqual(response.status_code, 409)
        history.assert_not_called()

    def test_sr_saved_replay_rejects_hash_mismatch(self):
        database = self.app.extensions["scalper_db"]
        saved = {"run_id": "run-1", "symbol": "EURUSD#", "data_sha256": "expected",
                 "parameters": {"slippage_points_per_side": 1,
                                "commission_per_lot_round_turn": 0,
                                "swap_long_per_lot_per_utc_rollover": 0,
                                "swap_short_per_lot_per_utc_rollover": 0,
                                "costs_confirmed": True},
                 "dataset": {"frames": {}, "contract": {}}}
        with patch.object(database, "list_sr_replay_runs", return_value=[{"run_id": "run-1"}]), \
             patch.object(database, "get_sr_replay_run", return_value=saved), \
             patch("scalperlab.web.run_sr_replay", return_value={"data_sha256": "different"}):
            response = self.client.post("/api/sr-quant/replay-saved", headers=self.headers,
                                        json={})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Hash", response.json["error"])

    def test_replay_does_not_compete_with_an_active_execution_engine(self):
        analyst = self.app.extensions["scalper_analyst"]
        with patch.object(analyst, "snapshot", return_value={"state": {"running": True}}):
            response = self.client.post("/api/analyst/replay", headers=self.headers, json={
                "symbol": "EURUSD#", "timeframe": "M15", "bars": 100,
                "costs_confirmed": True,
            })
        self.assertEqual(response.status_code, 409)
        self.assertIn("Pare os motores", response.json["error"])

    def test_replay_api_persists_snapshot_without_order_capability(self):
        bars = [{"time": 1_700_000_000 + index * 300, "open": 1.0,
                 "high": 1.01, "low": 0.999, "close": 1.001,
                 "spread": 1, "tick_volume": 100}
                for index in range(220)]
        contract = {"point": 0.0001, "trade_tick_size": 0.0001,
                    "trade_tick_value_profit": 1.0, "trade_tick_value_loss": 1.0,
                    "volume_min": 0.01, "volume_step": 0.01,
                    "trade_mode": 4, "chart_mode": 0}
        fake_port = SimpleNamespace(
            market_watch_catalog=lambda: {"available": True, "items": [
                {"broker_symbol": "EURUSD#", "trade_enabled": True}]},
            historical_market_data=lambda symbol, count, timeframe: {
                "ok": True, "symbol": symbol, "bars": bars, "contract": contract,
                "time_normalization": {"basis": "UTC", "server_utc_offset_seconds": 10800}},
            state=lambda: {"connected": True,
                           "account": {"login": "demo", "server": "Broker-DEMO", "mode": "DEMO"}},
        )
        self.app.extensions["scalper_mt5"] = fake_port
        response = self.client.post("/api/analyst/replay", headers=self.headers, json={
            "symbol": "EURUSD#", "timeframe": "M5", "bars": len(bars),
            "slippage_points": 1, "commission_per_lot_round_turn": 0,
            "swap_long_per_lot_per_utc_rollover": 0,
            "swap_short_per_lot_per_utc_rollover": 0, "costs_confirmed": True,
        })
        self.assertEqual(response.status_code, 200, response.json)
        self.assertIn("Nenhuma ordem", response.json["detail"])
        self.assertEqual(response.json["result"]["comparison"]["baseline_label"],
                         "Momentum de 20 candles: cruzamento do retorno para além de zero")
        self.assertEqual(response.json["result"]["parameters"]["development_fraction"], 0.70)
        runs = self.app.extensions["scalper_db"].list_replay_runs()
        self.assertEqual(len(runs), 1)
        saved = self.client.get(f"/api/analyst/replays/{runs[0]['run_id']}", headers=self.headers)
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(len(saved.json["replay"]["dataset"]["bars"]), len(bars))
        # Offline replay must not access any live connector capability.
        self.app.extensions["scalper_mt5"] = object()
        offline = self.client.post('/api/analyst/replay-saved', headers=self.headers, json={})
        self.assertEqual(offline.status_code, 200, offline.json)
        self.assertEqual(offline.json['result']['data_sha256'], response.json['result']['data_sha256'])
        self.assertTrue(offline.json['result']['offline'])
        with self.app.extensions['scalper_db'].connect() as db:
            db.execute("UPDATE replay_runs SET data_sha256='tampered'")
        bad = self.client.post('/api/analyst/replay-saved', headers=self.headers, json={})
        self.assertEqual(bad.status_code, 409)

    def test_home_embeds_per_process_token(self):
        response = self.client.get("/", headers={"Host": "127.0.0.1:5000"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'content="test-token"', response.data)
        policy = response.headers["Content-Security-Policy"].encode()
        self.assertIn("default-src 'self'".encode(), policy)

    def test_dashboard_hides_strategy_catalog_but_keeps_its_dedicated_view(self):
        response = self.client.get("/", headers={"Host": "127.0.0.1:5000"})
        html = response.get_data(as_text=True)
        dashboard = html.split('<section class="view active" id="view-dashboard">', 1)[1]
        dashboard = dashboard.split('<section class="view" id="view-strategies">', 1)[0]

        self.assertNotIn("Estratégias cadastradas", dashboard)
        self.assertIn('<section class="view" id="view-strategies">', html)
        self.assertIn("<h1>Estratégias</h1>", html)
        self.assertIn("Replay e validação cronológica", html)

    def test_home_rejects_unexpected_host(self):
        response = self.client.get("/", headers={"Host": "attacker.example"})
        self.assertEqual(response.status_code, 403)

    def test_oversized_request_is_rejected(self):
        response = self.client.post("/api/strategies", headers=self.headers,
                                    data=b" " * (self.app.config["MAX_CONTENT_LENGTH"] + 1),
                                    content_type="application/json")
        self.assertEqual(response.status_code, 413)


if __name__ == "__main__":
    unittest.main()
