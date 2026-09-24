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
        self.targeted_orders = []
        self.targeted_deals = []
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

    def history_order_by_ticket(self, ticket: int):
        return {
            "available": self.history_available,
            "items": [item for item in self.targeted_orders if item.get("ticket") == ticket]
            if self.history_available
            else [],
        }

    def history_deals_by_position(self, position_ticket: int):
        return {
            "available": self.history_available,
            "items": [
                item for item in self.targeted_deals if item.get("position_id") == position_ticket
            ]
            if self.history_available
            else [],
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

    def test_smoke_test_with_open_test_position_stays_partial(self):
        correlation_id = "abcdef0123456789abcdef0123456789"
        marker = f"SC{correlation_id[:10]}".upper()
        connector = HistoryConnector(self.database, matching_history=True)
        connector.orders = [{"ticket": 801, "comment": marker, "symbol": "EURUSD.a"}]
        connector.deals = [
            {
                "ticket": 802,
                "order": 801,
                "comment": marker,
                "symbol": "EURUSD.a",
                "entry": 0,
                "volume": 0.01,
                "price": 1.1,
            }
        ]
        connector.open_positions = [
            {
                "ticket": 801,
                "comment": marker,
                "symbol": "EURUSD.a",
                "volume": 0.01,
                "magic": 209221001,
            }
        ]
        self.database.create_trade_audit(
            correlation_id=correlation_id,
            terminal_id=connector.terminal_id,
            method="place_demo_smoke_order",
            started_at="2026-09-24T12:00:00+00:00",
            request={"broker_marker": marker, "canonical_symbol": "EURUSD"},
        )
        self.database.update_trade_audit(
            correlation_id,
            status="partial",
            result={"ok": False, "partial": True, "position_remains": True},
        )
        audited = AuditedTradingPort(connector, self.database)

        reconciled = audited.reconcile(correlation_id)

        self.assertEqual(reconciled["status"], "partial")

    def test_successful_close_and_absent_position_reconcile_without_history_ticket(self):
        correlation_id = "1234567890abcdef1234567890abcdef"
        connector = HistoryConnector(self.database, matching_history=False)
        self.database.create_trade_audit(
            correlation_id=correlation_id,
            terminal_id=connector.terminal_id,
            method="close_demo_position",
            started_at="2026-09-24T12:00:00+00:00",
            request={"ticket": 801},
        )
        self.database.update_trade_audit(
            correlation_id,
            status="acknowledged",
            result={"ok": True, "retcode": 10009, "correlation_id": correlation_id},
        )

        reconciled = AuditedTradingPort(connector, self.database).reconcile(correlation_id)

        self.assertEqual(reconciled["status"], "reconciled")
        self.assertFalse(reconciled["evidence"]["match_found"])
        self.assertTrue(reconciled["evidence"]["closure_confirmed"])

    def test_smoke_test_links_a_later_audited_close_for_its_position(self):
        smoke_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        close_id = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        connector = HistoryConnector(self.database, matching_history=False)
        self.database.create_trade_audit(
            correlation_id=smoke_id,
            terminal_id=connector.terminal_id,
            method="place_demo_smoke_order",
            started_at="2026-09-24T12:00:00+00:00",
            request={"broker_marker": f"SC{smoke_id[:10]}"},
        )
        self.database.update_trade_audit(
            smoke_id,
            status="partial",
            result={"ok": False, "open_order": 801, "position_remains": True},
        )
        self.database.create_trade_audit(
            correlation_id=close_id,
            terminal_id=connector.terminal_id,
            method="close_demo_position",
            started_at="2026-09-24T12:01:00+00:00",
            request={"ticket": 801},
        )
        self.database.update_trade_audit(
            close_id,
            status="reconciled",
            result={"ok": True},
            evidence={"closure_confirmed": True},
        )

        reconciled = AuditedTradingPort(connector, self.database).reconcile(smoke_id)

        self.assertEqual(reconciled["status"], "reconciled")
        self.assertTrue(reconciled["evidence"]["closure_confirmed"])
        self.assertEqual(reconciled["evidence"]["follow_up_close_correlation_id"], close_id)

    def test_smoke_result_and_absent_position_confirm_close_without_history_deals(self):
        correlation_id = "cccccccccccccccccccccccccccccccc"
        connector = HistoryConnector(self.database, matching_history=False)
        self.database.create_trade_audit(
            correlation_id=correlation_id,
            terminal_id=connector.terminal_id,
            method="place_demo_smoke_order",
            started_at="2026-09-24T12:00:00+00:00",
            request={"broker_marker": f"SC{correlation_id[:10]}"},
        )
        self.database.update_trade_audit(
            correlation_id,
            status="acknowledged",
            result={
                "ok": True,
                "filled_volume": 0.01,
                "filled_price": 1.1,
                "position_remains": False,
                "close": {"ok": True, "filled_volume": 0.01, "filled_price": 1.101},
            },
        )

        reconciled = AuditedTradingPort(connector, self.database).reconcile(correlation_id)

        self.assertEqual(reconciled["status"], "reconciled")
        self.assertTrue(reconciled["evidence"]["closure_confirmed"])
        self.assertEqual(reconciled["evidence"]["filled_volume"], 0.01)
        self.assertEqual(reconciled["evidence"]["closed_volume"], 0.01)
        self.assertEqual(reconciled["evidence"]["weighted_close_price"], 1.101)

    def test_smoke_reconciles_from_ticket_queries_when_time_window_has_no_rows(self):
        correlation_id = "dddddddddddddddddddddddddddddddd"
        connector = HistoryConnector(self.database, matching_history=False)
        connector.targeted_orders = [
            {"ticket": 801, "position_id": 800, "symbol": "EURUSD#", "volume_initial": 0.01},
            {"ticket": 803, "position_id": 800, "symbol": "EURUSD#", "volume_initial": 0.01},
        ]
        connector.targeted_deals = [
            {
                "ticket": 802,
                "order": 801,
                "position_id": 800,
                "entry": 0,
                "symbol": "EURUSD#",
                "volume": 0.01,
                "price": 1.1,
            },
            {
                "ticket": 804,
                "order": 803,
                "position_id": 800,
                "entry": 1,
                "symbol": "EURUSD#",
                "volume": 0.01,
                "price": 1.101,
            },
        ]
        self.database.create_trade_audit(
            correlation_id=correlation_id,
            terminal_id=connector.terminal_id,
            method="place_demo_smoke_order",
            started_at="2026-09-24T12:00:00+00:00",
            request={"broker_marker": f"SC{correlation_id[:10]}"},
        )
        self.database.update_trade_audit(
            correlation_id,
            status="acknowledged",
            result={
                "ok": True,
                "open_order": 801,
                "open_deal": 802,
                "position_remains": False,
                "close": {
                    "ok": True,
                    "order": 803,
                    "deal": 804,
                    "filled_volume": 0.01,
                    "filled_price": 1.101,
                },
            },
        )

        reconciled = AuditedTradingPort(connector, self.database).reconcile(correlation_id)

        self.assertEqual(reconciled["status"], "reconciled")
        self.assertTrue(reconciled["evidence"]["match_found"])
        self.assertEqual({item["ticket"] for item in reconciled["evidence"]["orders"]}, {801, 803})
        self.assertEqual({item["ticket"] for item in reconciled["evidence"]["deals"]}, {802, 804})
        self.assertEqual(reconciled["evidence"]["closed_volume"], 0.01)
        self.assertEqual(reconciled["evidence"]["weighted_close_price"], 1.101)


if __name__ == "__main__":
    unittest.main()
