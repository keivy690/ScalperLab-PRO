import tempfile
import unittest
from pathlib import Path

from scalperlab.db import Database
from scalperlab.mt5_gateway import MT5Gateway
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

    def test_home_embeds_per_process_token(self):
        response = self.client.get("/", headers={"Host": "127.0.0.1:5000"})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'content="test-token"', response.data)
        policy = response.headers["Content-Security-Policy"].encode()
        self.assertIn("default-src 'self'".encode(), policy)

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
