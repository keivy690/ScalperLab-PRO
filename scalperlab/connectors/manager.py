from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from ..config import data_directory
from .discovery import discover_mt5_terminals
from .mt5 import MT5Connector


@dataclass(slots=True)
class TerminalConfig:
    terminal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = "MetaTrader 5"
    path: str | None = None
    enabled: bool = True
    selected_symbols: list[str] = field(default_factory=list)
    symbol_mappings: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.terminal_id.strip():
            raise ValueError("terminal_id é obrigatório.")
        self.symbol_mappings = {key.upper(): value for key, value in self.symbol_mappings.items()}


class ConnectorManager:
    """Owns terminal configurations and one lazy connector per terminal ID."""

    def __init__(self, config_path: Path | None = None,
                 connector_factory: Callable[[TerminalConfig], MT5Connector] | None = None) -> None:
        self.config_path = config_path or (data_directory() / "terminals.json")
        self.connector_factory = connector_factory or (
            lambda config: MT5Connector(terminal_id=config.terminal_id,
                                        terminal_path=config.path,
                                        symbol_mappings=config.symbol_mappings))
        self._configs: dict[str, TerminalConfig] = {}
        self._connectors: dict[str, MT5Connector] = {}
        self._load()
        if not self._configs:
            default_config = TerminalConfig(terminal_id="default", name="Terminal padrão")
            self.add_terminal(default_config, persist=False)

    def _load(self) -> None:
        try:
            rows = json.loads(self.config_path.read_text(encoding="utf-8"))
            self._configs = {row["terminal_id"]: TerminalConfig(**row) for row in rows}
        except FileNotFoundError:
            return
        except (OSError, ValueError, TypeError, KeyError):
            self._configs = {}

    def _save(self) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        temporary.write_text(json.dumps([asdict(item) for item in self._configs.values()],
                                        ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.config_path)

    def add_terminal(self, config: TerminalConfig, *, persist: bool = True) -> None:
        if config.terminal_id in self._configs:
            raise ValueError(f"Terminal já cadastrado: {config.terminal_id}")
        self._configs[config.terminal_id] = config
        if persist:
            self._save()

    def update_terminal(self, config: TerminalConfig) -> None:
        if config.terminal_id not in self._configs:
            raise KeyError(config.terminal_id)
        connector = self._connectors.pop(config.terminal_id, None)
        if connector:
            connector.shutdown()
        self._configs[config.terminal_id] = config
        self._save()

    def remove_terminal(self, terminal_id: str) -> None:
        if terminal_id not in self._configs:
            raise KeyError(terminal_id)
        connector = self._connectors.pop(terminal_id, None)
        if connector:
            connector.shutdown()
        del self._configs[terminal_id]
        self._save()

    def terminals(self) -> list[TerminalConfig]:
        return list(self._configs.values())

    def discover_terminals(self) -> list[Path]:
        return discover_mt5_terminals()

    def set_selected_symbols(self, terminal_id: str, symbols: list[str]) -> TerminalConfig:
        config = self._configs.get(terminal_id)
        if config is None:
            raise KeyError(terminal_id)
        config.selected_symbols = list(dict.fromkeys(symbols))
        self._save()
        return config

    def get_connector(self, terminal_id: str = "default") -> MT5Connector:
        config = self._configs.get(terminal_id)
        if config is None or not config.enabled:
            raise KeyError(f"Terminal inexistente ou desativado: {terminal_id}")
        if terminal_id not in self._connectors:
            self._connectors[terminal_id] = self.connector_factory(config)
        return self._connectors[terminal_id]

    def shutdown(self) -> None:
        for connector in self._connectors.values():
            connector.shutdown()
        self._connectors.clear()
