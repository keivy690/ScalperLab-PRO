from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from scalperlab.connectors.manager import ConnectorManager, TerminalConfig
from scalperlab.connectors.process import ConnectorLifecycle, ProcessMT5Connector
from scalperlab.trading.ports import ConnectorV1


class FakeConnector:
    def __init__(self, config):
        self.terminal_id = config.terminal_id
        self.calls = 0
        self.armed = False

    def state(self):
        self.calls += 1
        login = "2002" if self.terminal_id == "changes-account" and self.calls >= 6 else "1001"
        return {
            "connected": True, "status": "conectado", "detail": None,
            "account": {"login": login, "server": "DemoServer"},
            "terminal": {"trade_allowed": True}, "demo_armed": self.armed,
            "emergency_action": {},
        }

    def terminal_state(self):
        return self.state()

    def account_state(self):
        return self.state()["account"]

    def arm_order_engine(self, _engine, _mode="DEMO", _fingerprint=None):
        self.armed = True
        return True

    def disarm_order_engine(self, _engine):
        self.armed = False

    def shutdown(self):
        self.armed = False


def fake_connector_factory(config):
    return FakeConnector(config)


class ConnectorProcessTests(unittest.TestCase):
    def make_connector(self, terminal_id="fake", **kwargs):
        return ProcessMT5Connector(
            TerminalConfig(terminal_id=terminal_id),
            connector_factory=fake_connector_factory,
            heartbeat_interval=kwargs.pop("heartbeat_interval", 0.05),
            rpc_timeout=1.0, restart_delay=0.05, max_restart_delay=0.1, **kwargs)

    def test_worker_reaches_ready_and_reports_account_identity(self):
        connector = self.make_connector()
        try:
            self.assertTrue(connector.wait_until_ready(5))
            state = connector.state()
            self.assertEqual(connector.health().lifecycle, ConnectorLifecycle.READY)
            self.assertEqual(connector.health().account_fingerprint, "1001@DemoServer")
            self.assertEqual(state["connector"]["terminal_id"], "fake")
            self.assertIsNotNone(connector.health().last_heartbeat)
        finally:
            connector.shutdown()

    def test_account_identity_change_is_observed_by_heartbeat(self):
        connector = self.make_connector("changes-account")
        try:
            self.assertTrue(connector.wait_until_ready(5))
            self.assertTrue(connector.arm_order_engine("strategy", "DEMO", "1001@DemoServer"))
            deadline = time.monotonic() + 5
            while not connector.health().identity_changed and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(connector.health().identity_changed)
            self.assertEqual(connector.health().account_fingerprint, "2002@DemoServer")
            self.assertFalse(connector.state()["demo_armed"])
        finally:
            connector.shutdown()

    def test_dead_worker_is_restarted_after_backoff(self):
        connector = self.make_connector()
        try:
            self.assertTrue(connector.wait_until_ready(5))
            original_pid = connector.health().worker_pid
            # Prevent the heartbeat from closing this Windows handle while the
            # test is waiting on the deliberately terminated child process.
            with connector._rpc_lock:
                connector._process.terminate()
                connector._process.join(timeout=2)
            deadline = time.monotonic() + 6
            restarted = False
            while time.monotonic() < deadline:
                if connector.wait_until_ready(0.1):
                    health = connector.health()
                    if health.worker_pid and health.worker_pid != original_pid:
                        restarted = True
                        break
                time.sleep(0.05)
            self.assertTrue(restarted, connector.health())
            self.assertGreaterEqual(connector.health().restart_count, 1)
        finally:
            connector.shutdown()

    def test_manager_uses_process_isolated_connector_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConnectorManager(config_path=Path(directory) / "terminals.json")
            connector = manager.get_connector()
            self.assertIsInstance(connector, ProcessMT5Connector)
            manager.shutdown()

    def test_process_proxy_implements_connector_v1_contract(self):
        connector = ProcessMT5Connector(TerminalConfig(terminal_id="contract"),
                                        start_immediately=False)
        try:
            self.assertIsInstance(connector, ConnectorV1)
        finally:
            connector.shutdown()

    def test_trade_rpc_has_longer_timeout_and_timeout_is_non_retryable_unknown(self):
        class FakePipe:
            def __init__(self):
                self.timeout = None
            def send(self, _message): pass
            def poll(self, timeout):
                self.timeout = timeout
                return False
            def close(self): pass

        class FakeWorker:
            def __init__(self):
                self.alive = True
            def is_alive(self): return self.alive
            def terminate(self): self.alive = False
            def join(self, timeout=None): pass
            def close(self): pass

        connector = ProcessMT5Connector(
            TerminalConfig(terminal_id="timeout"), start_immediately=False,
            rpc_timeout=1.0, trade_rpc_timeout=30.0)
        pipe = FakePipe()
        connector._process = FakeWorker()
        connector._connection = pipe
        try:
            result = connector.place_demo_smoke_order("ENVIAR TESTE DEMO")
            self.assertEqual(pipe.timeout, 30.0)
            self.assertFalse(result["ok"])
            self.assertTrue(result["unknown"])
            self.assertTrue(result["no_retry"])
            self.assertTrue(result["position_may_remain"])
        finally:
            connector.shutdown()

    def test_two_terminal_ids_run_in_separate_worker_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConnectorManager(
                config_path=Path(directory) / "terminals.json",
                connector_factory=lambda config: ProcessMT5Connector(
                    config, connector_factory=fake_connector_factory, heartbeat_interval=0.05,
                    restart_delay=0.05, max_restart_delay=0.1),
            )
            manager.add_terminal(TerminalConfig(terminal_id="broker-a"))
            manager.add_terminal(TerminalConfig(terminal_id="broker-b"))
            first = manager.get_connector("broker-a")
            second = manager.get_connector("broker-b")
            try:
                self.assertTrue(first.wait_until_ready(5))
                self.assertTrue(second.wait_until_ready(5))
                self.assertNotEqual(first.health().worker_pid, second.health().worker_pid)
            finally:
                manager.shutdown()


if __name__ == "__main__":
    unittest.main()
