from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scalperlab.connectors.audit import AuditedTradingPort
from scalperlab.db import Database


class HistoryConnector:
    terminal_id = "demo-terminal"

    def __init__(
        self, database: Database, *, matching_history: bool, history_available: bool = True
    ):
        self.database = database
        self.matching_history = matching_history
        self.history_available = history_available
        self.calls = 0
        self.orders = []
        self.deals = []
        self.open_positions = []

    def state(self):
        return {"connected": True, "account": {"login": "12345", "server": "DemoServer"}}

    def positions(self):
        return {"available": True, "items": list(self.open_positions)}

    def history_orders(self, _date_from: str, _date_to: str):
        return {
            "available": self.history_available,
            "items": list(self.orders) if self.history_available else [],
        }

    def history_deals(self, _date_from: str, _date_to: str):
        return {
            "available": self.history_available,
            "items": list(self.deals) if self.history_available else [],
        }

    def send_demo_strategy_order(
        self,
        symbol,
        side,
        volume,
        stop,
        target,
        strategy_id,
        expected_account_fingerprint=None,
        risk_cash=None,
        correlation_id=None,
    ):
        self.calls += 1
        row = self.database.get_trade_audit(correlation_id)
        assert row["status"] == "prepared"
        marker = f"SC{correlation_id.replace('-', '')[:10]}".upper()
        if self.matching_history:
            self.orders = [
                {
                    "ticket": 801,
                    "comment": f"{marker} SL1 S{strategy_id}",
                    "symbol": symbol,
                    "magic": 209221051,
                    "state": 4,
                    "volume_initial": volume,
                    "volume_current": 0,
                }
            ]
            self.deals = [
                {
                    "ticket": 802,
                    "order": 801,
                    "comment": f"{marker} SL1 S{strategy_id}",
                    "symbol": symbol,
                    "entry": 0,
                    "volume": volume,
                    "price": 1.101,
                    "commission": -0.1,
                    "swap": 0.0,
                    "fee": 0.0,
                    "profit": 0.0,
                }
            ]
        return {
            "ok": False,
            "unknown": True,
            "no_retry": True,
            "detail": "Simulated lost response after server acceptance.",
        }


class ConnectorAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Database(Path(self.temp.name) / "audit.sqlite3")

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, connector):
        audited = AuditedTradingPort(
            connector, self.database, symbol_mappings={"EURUSD": "EURUSD.a"}
        )
        return audited.send_demo_strategy_order(
            "EURUSD",
            "BUY",
            0.01,
            1.09,
            1.12,
            1,
            expected_account_fingerprint="12345@DemoServer",
            risk_cash=5.0,
        )

    def test_unknown_order_is_correlated_and_reconciled_from_history(self):
        connector = HistoryConnector(self.database, matching_history=True)
        result = self.invoke(connector)
        record = self.database.get_trade_audit(result["correlation_id"])
        self.assertEqual(connector.calls, 1)
        self.assertTrue(result["unknown"])
        self.assertEqual(record["status"], "reconciled")
        self.assertEqual(record["request"]["canonical_symbol"], "EURUSD")
        self.assertEqual(record["request"]["broker_symbol"], "EURUSD.a")
        self.assertNotIn("12345@DemoServer", str(record["request"]))
        self.assertEqual(record["evidence"]["filled_volume"], 0.01)
        self.assertAlmostEqual(record["evidence"]["weighted_fill_price"], 1.101)
        self.assertEqual(record["evidence"]["costs"]["commission"], -0.1)
        restarted_database = Database(self.database.path)
        self.assertEqual(
            restarted_database.get_trade_audit(result["correlation_id"])["status"], "reconciled"
        )

    def test_unavailable_match_remains_pending_until_a_later_read_reconciles(self):
        connector = HistoryConnector(self.database, matching_history=False)
        result = self.invoke(connector)
        record = self.database.get_trade_audit(result["correlation_id"])
        self.assertEqual(record["status"], "pending_reconciliation")
        self.assertEqual(connector.calls, 1)

        marker = record["request"]["broker_marker"]
        connector.orders = [{"ticket": 901, "comment": f"{marker} order", "symbol": "EURUSD.a"}]
        reconciled = AuditedTradingPort(connector, self.database).reconcile_pending(
            correlation_id=result["correlation_id"]
        )
        self.assertEqual(reconciled[0]["status"], "reconciled")
        self.assertEqual(connector.calls, 1)
        self.assertEqual(
            self.database.get_trade_audit(result["correlation_id"])["status"], "reconciled"
        )

    def test_unavailable_history_never_marks_unknown_order_reconciled(self):
        connector = HistoryConnector(self.database, matching_history=True, history_available=False)
        result = self.invoke(connector)
        record = self.database.get_trade_audit(result["correlation_id"])
        self.assertEqual(record["status"], "pending_reconciliation")
        self.assertFalse(record["evidence"]["history_orders_available"])
        self.assertFalse(record["evidence"]["history_deals_available"])

    def test_partial_close_with_position_remaining_stays_partial_after_reconciliation(self):
        correlation_id = "0123456789abcdef0123456789abcdef"
        marker = f"SC{correlation_id[:10]}".upper()
        connector = HistoryConnector(self.database, matching_history=False)
        connector.orders = [{"ticket": 801, "comment": f"{marker} close", "symbol": "EURUSD.a"}]
        connector.deals = [
            {
                "ticket": 802,
                "order": 801,
                "comment": f"{marker} close",
                "symbol": "EURUSD.a",
                "entry": 1,
                "volume": 0.004,
                "price": 1.1,
            }
        ]
        connector.open_positions = [
            {"ticket": 801, "comment": "position", "symbol": "EURUSD.a", "volume": 0.006}
        ]
        self.database.create_trade_audit(
            correlation_id=correlation_id,
            terminal_id=connector.terminal_id,
            method="close_demo_position",
            started_at="2026-09-24T12:00:00+00:00",
            request={"ticket": 801, "broker_marker": marker},
        )
        self.database.update_trade_audit(
            correlation_id,
            status="partial",
            result={"ok": False, "partial": True, "correlation_id": correlation_id},
        )

        reconciled = AuditedTradingPort(connector, self.database).reconcile(correlation_id)

        self.assertEqual(reconciled["status"], "partial")
        self.assertEqual(reconciled["evidence"]["closed_volume"], 0.004)
        self.assertEqual(len(reconciled["evidence"]["positions"]), 1)


if __name__ == "__main__":
    unittest.main()
