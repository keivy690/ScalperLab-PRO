from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scalperlab.connectors.manager import ConnectorManager, TerminalConfig
from scalperlab.trading.models import Symbol
from scalperlab.trading.ports import ConnectorV1


class TradingAbstractionTests(unittest.TestCase):
    def test_symbol_keeps_canonical_and_broker_names_and_contract_metadata(self):
        symbol = Symbol.from_broker_info(SimpleNamespace(
            name="EURUSD.a", digits=5, trade_tick_size=0.00001,
            volume_min=0.01, volume_step=0.01, trade_mode=4, visible=True,
        ), canonical_symbol="EURUSD")

        self.assertEqual(symbol.canonical_symbol, "EURUSD")
        self.assertEqual(symbol.broker_symbol, "EURUSD.a")
        self.assertEqual(symbol.tick_size, 0.00001)
        self.assertTrue(symbol.trade_enabled)
        self.assertTrue(symbol.visible)
        close_only = Symbol.from_broker_info(SimpleNamespace(
            name="EURUSD", digits=5, trade_mode=3,
        ))
        self.assertFalse(close_only.trade_enabled)

    def test_terminal_configs_have_independent_ids_and_selected_symbols(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "terminals.json"
            def factory(_config):
                return object()

            manager = ConnectorManager(config_path=config_path, connector_factory=factory)
            manager.add_terminal(TerminalConfig(
                terminal_id="broker-a", name="Broker A", path="C:/A/terminal64.exe",
                selected_symbols=["EURUSD"], symbol_mappings={"EURUSD": "EURUSD.a"},
            ))
            manager.add_terminal(TerminalConfig(
                terminal_id="broker-b", name="Broker B", path="C:/B/terminal64.exe",
            ))

            reloaded = ConnectorManager(config_path=config_path, connector_factory=factory)
            by_id = {config.terminal_id: config for config in reloaded.terminals()}
            self.assertEqual(set(by_id), {"default", "broker-a", "broker-b"})
            self.assertEqual(by_id["broker-a"].selected_symbols, ["EURUSD"])
            self.assertEqual(by_id["broker-a"].symbol_mappings["EURUSD"], "EURUSD.a")
            self.assertEqual(by_id["broker-b"].selected_symbols, [])

    def test_available_and_market_watch_sets_are_explicitly_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = ConnectorManager(config_path=Path(directory) / "terminals.json")
            connector = manager.get_connector()
            self.assertIsInstance(connector, ConnectorV1)
            connector._connect = lambda: SimpleNamespace(symbols_get=lambda: [
                SimpleNamespace(name="EURUSD", digits=5, trade_tick_size=0.00001,
                                volume_min=0.01, volume_step=0.01, trade_mode=4, visible=True),
                SimpleNamespace(name="GBPUSD", digits=5, trade_tick_size=0.00001,
                                volume_min=0.01, volume_step=0.01, trade_mode=4, visible=False),
            ])

            self.assertEqual({item.broker_symbol for item in connector.available_symbols()},
                             {"EURUSD", "GBPUSD"})
            self.assertEqual({item.broker_symbol for item in connector.market_watch_symbols()},
                             {"EURUSD"})


if __name__ == "__main__":
    unittest.main()
