from __future__ import annotations

import multiprocessing
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from multiprocessing.connection import Connection
from typing import Any, Callable

from ..mt5_gateway import MT5Gateway
from ..trading.models import Symbol


class ConnectorLifecycle(StrEnum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    READY = "ready"
    DEGRADED = "degraded"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ConnectorHealth:
    terminal_id: str
    lifecycle: ConnectorLifecycle
    worker_pid: int | None
    last_heartbeat: str | None
    last_error: str | None
    account_fingerprint: str | None
    identity_changed: bool
    restart_count: int


_REMOTE_METHODS = {
    "terminal_state", "account_state", "available_symbols", "market_watch_symbols", "market_watch_catalog",
    "tick", "rates", "orders", "positions", "history_orders", "history_deals",
    "history_order_by_ticket", "history_deals_by_position",
    "submit_order", "state",
    "validate_market_symbols", "strategy_market_data", "historical_market_data", "current_tick", "economic_calendar",
    "risk_volume", "arm_order_engine", "disarm_order_engine",
    "send_demo_strategy_order", "send_real_strategy_order",
    "send_demo_analyst_order", "send_real_analyst_order", "arm_demo",
    "arm_real_closing", "place_demo_smoke_order", "close_demo_position",
    "close_real_position", "emergency_stop_demo", "emergency_stop_real",
    "set_emergency_action", "update_emergency_action",
}

_TRADE_ACTION_METHODS = {
    "submit_order", "send_demo_strategy_order", "send_real_strategy_order",
    "send_demo_analyst_order", "send_real_analyst_order",
    "place_demo_smoke_order", "close_demo_position", "close_real_position",
    "emergency_stop_demo", "emergency_stop_real",
}


def _connector_worker(connection: Connection, config: Any,
                      connector_factory: Callable[[Any], Any] | None) -> None:
    connector = connector_factory(config) if connector_factory else MT5Gateway(
        terminal_id=config.terminal_id, terminal_path=config.path,
        symbol_mappings=config.symbol_mappings)
    previous_fingerprint = None
    try:
        while True:
            try:
                request_id, method, args, kwargs = connection.recv()
            except (EOFError, OSError):
                break
            if method == "__shutdown__":
                connector.shutdown()
                connection.send((request_id, True, None))
                break
            try:
                result = getattr(connector, method)(*args, **kwargs)
                if method in {"state", "terminal_state"}:
                    account = result.get("account") or {}
                    fingerprint = (f"{account['login']}@{account['server']}"
                                   if account.get("login") and account.get("server") else None)
                    if previous_fingerprint and fingerprint != previous_fingerprint:
                        connector.disarm_order_engine("strategy")
                        connector.disarm_order_engine("analyst")
                    if fingerprint:
                        previous_fingerprint = fingerprint
                connection.send((request_id, True, result))
            except Exception as exc:
                connection.send((request_id, False, f"{type(exc).__name__}: {exc}"))
    finally:
        try:
            connector.shutdown()
        except Exception:
            pass
        connection.close()


class ProcessMT5Connector:
    """RPC proxy with a dedicated MT5 process, heartbeat and bounded restart backoff."""

    def __init__(self, config: Any, connector_factory: Callable[[Any], Any] | None = None, *,
                 heartbeat_interval: float = 5.0, rpc_timeout: float = 4.0,
                 trade_rpc_timeout: float = 30.0,
                 restart_delay: float = 1.0, max_restart_delay: float = 30.0,
                 start_immediately: bool = True) -> None:
        self.terminal_id = config.terminal_id
        self._config = config
        self._factory = connector_factory
        self._heartbeat_interval = max(0.05, heartbeat_interval)
        self._rpc_timeout = max(0.05, rpc_timeout)
        self._trade_rpc_timeout = max(self._rpc_timeout, trade_rpc_timeout)
        self._restart_delay = max(0.05, restart_delay)
        self._max_restart_delay = max(self._restart_delay, max_restart_delay)
        self._ctx = multiprocessing.get_context("spawn")
        self._rpc_lock = threading.RLock()
        self._health_lock = threading.RLock()
        self._stopping = threading.Event()
        self._process = None
        self._connection: Connection | None = None
        self._request_id = 0
        self._next_start_at = 0.0
        self._last_heartbeat = None
        self._last_error = None
        self._account_fingerprint = None
        self._identity_changed = False
        self._restart_count = 0
        self._lifecycle = ConnectorLifecycle.DISCONNECTED
        self.emergency_action = {
            "status": "idle", "detail": "Nenhuma parada de emergência executada nesta sessão.",
            "updated_at": None, "remaining_count": None, "reconciled": False,
        }
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, name=f"mt5-heartbeat-{self.terminal_id}", daemon=True)
        if start_immediately:
            self.start()
            self._heartbeat_thread.start()

    def start(self) -> None:
        with self._rpc_lock:
            if self._stopping.is_set() or time.monotonic() < self._next_start_at:
                return
            if self._process is not None and self._process.is_alive():
                return
            self._lifecycle = ConnectorLifecycle.CONNECTING
            parent, child = self._ctx.Pipe(duplex=True)
            process = self._ctx.Process(
                target=_connector_worker, args=(child, self._config, self._factory),
                name=f"ScalperLab-MT5-{self.terminal_id}", daemon=True)
            try:
                process.start()
            except Exception as exc:
                parent.close()
                child.close()
                self._mark_failure(
                    f"Falha ao iniciar o processo do conector ({type(exc).__name__}).", fatal=True)
                return
            child.close()
            self._connection = parent
            self._process = process

    def _mark_failure(self, message: str, *, fatal: bool = False) -> None:
        with self._health_lock:
            self._last_error = message
            self._lifecycle = ConnectorLifecycle.ERROR if fatal else ConnectorLifecycle.DEGRADED
            self._restart_count += 1
            delay = min(self._restart_delay * 2 ** min(self._restart_count - 1, 8),
                        self._max_restart_delay)
            self._next_start_at = time.monotonic() + delay

    def _close_transport(self) -> None:
        process = self._process
        if process is not None and not process.is_alive():
            try:
                process.join(timeout=0)
                process.close()
            except (AssertionError, ValueError):
                pass
        if self._connection:
            try:
                self._connection.close()
            except OSError:
                pass
        self._connection = None
        self._process = None

    def _terminate_worker(self) -> None:
        process = self._process
        if process is not None and process.is_alive():
            process.terminate()
            process.join(timeout=1)
        self._close_transport()

    def _rpc(self, method: str, *args, **kwargs):
        if method not in _REMOTE_METHODS:
            raise AttributeError(method)
        with self._rpc_lock:
            if self._stopping.is_set():
                return False, "Conector encerrado."
            if self._process is None or not self._process.is_alive():
                if self._process is not None:
                    self._mark_failure("O processo do conector terminou inesperadamente.")
                    self._close_transport()
                self.start()
            if self._process is None or not self._process.is_alive() or self._connection is None:
                return False, "Conector indisponível; reconexão agendada."
            self._request_id += 1
            request_id = self._request_id
            try:
                self._connection.send((request_id, method, args, kwargs))
                timeout = (self._trade_rpc_timeout if method in _TRADE_ACTION_METHODS
                           else self._rpc_timeout)
                if not self._connection.poll(timeout):
                    self._mark_failure(f"Timeout ao aguardar resposta do conector ({method}).")
                    self._terminate_worker()
                    return False, self._last_error
                response_id, ok, result = self._connection.recv()
                if response_id != request_id:
                    self._mark_failure("Resposta do conector fora de sequência.")
                    self._terminate_worker()
                    return False, self._last_error
                if not ok:
                    self._last_error = str(result)
                    return False, self._last_error
                self._last_heartbeat = datetime.now(timezone.utc).isoformat(timespec="seconds")
                self._last_error = None
                self._next_start_at = 0
                return True, result
            except (EOFError, OSError, BrokenPipeError) as exc:
                self._mark_failure(f"Comunicação interrompida ({type(exc).__name__}).")
                self._terminate_worker()
                return False, self._last_error

    def _observe(self, state: dict[str, Any]) -> None:
        account = state.get("account") or {}
        fingerprint = (f"{account['login']}@{account['server']}"
                       if account.get("login") and account.get("server") else None)
        with self._health_lock:
            if self._account_fingerprint and fingerprint != self._account_fingerprint:
                self._identity_changed = True
            if fingerprint:
                self._account_fingerprint = fingerprint
            self._lifecycle = (ConnectorLifecycle.READY
                               if state.get("connected") and fingerprint
                               else ConnectorLifecycle.DEGRADED)
            if not state.get("connected"):
                self._last_error = state.get("detail") or "Terminal desconectado."

    def _heartbeat_loop(self) -> None:
        while not self._stopping.wait(self._heartbeat_interval):
            ok, state = self._rpc("state")
            if ok:
                self._observe(state)

    def health(self) -> ConnectorHealth:
        with self._health_lock:
            process = self._process
            try:
                worker_pid = process.pid if process and process.is_alive() else None
            except (AssertionError, ValueError):
                # A dead multiprocessing handle may be closed concurrently while
                # the transport is being replaced after a worker failure.
                worker_pid = None
            return ConnectorHealth(
                self.terminal_id, self._lifecycle,
                worker_pid,
                self._last_heartbeat, self._last_error, self._account_fingerprint,
                self._identity_changed, self._restart_count)

    def wait_until_ready(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._stopping.is_set():
            if self.health().lifecycle == ConnectorLifecycle.READY:
                return True
            self._stopping.wait(0.05)
        return False

    def state(self) -> dict[str, Any]:
        ok, state = self._rpc("state")
        if not ok:
            return {"connected": False, "status": self.health().lifecycle.value,
                    "detail": state, "account": None, "terminal": None,
                    "demo_armed": False, "real_trading": "disponivel_com_confirmacao",
                    "emergency_action": dict(self.emergency_action)}
        self._observe(state)
        state["connector"] = asdict(self.health())
        state["connector"]["lifecycle"] = state["connector"]["lifecycle"].value
        return state

    def terminal_state(self) -> dict[str, Any]:
        state = self.state()
        return {"terminal_id": self.terminal_id, "connected": state.get("connected", False),
                "status": state.get("status"), "detail": state.get("detail"),
                "terminal": state.get("terminal"), "account": state.get("account"),
                "connector": state.get("connector")}

    def account_state(self) -> dict[str, Any]:
        ok, result = self._rpc("account_state")
        return result if ok else {}

    def available_symbols(self) -> list[Symbol]:
        ok, result = self._rpc("available_symbols")
        return result if ok else []

    def market_watch_symbols(self) -> list[Symbol]:
        ok, result = self._rpc("market_watch_symbols")
        return result if ok else []

    def market_watch_catalog(self) -> dict[str, Any]:
        ok, result = self._rpc("market_watch_catalog")
        return result if ok else {"available": False, "source": "MT5 Market Watch",
                                  "count": 0, "items": [], "detail": result}

    def tick(self, broker_symbol: str) -> dict[str, Any]:
        ok, result = self._rpc("tick", broker_symbol)
        return result if ok else {"ok": False, "detail": result}

    def rates(self, broker_symbol: str, timeframe: str, count: int) -> dict[str, Any]:
        ok, result = self._rpc("rates", broker_symbol, timeframe, count)
        return result if ok else {"ok": False, "detail": result}

    def historical_market_data(self, symbol_name: str, count: int = 1200,
                               timeframe: str = "M15") -> dict[str, Any]:
        ok, result = self._rpc("historical_market_data", symbol_name, count, timeframe)
        return result if ok else {"ok": False, "detail": result}

    def orders(self) -> dict[str, Any]:
        ok, result = self._rpc("orders")
        return result if ok else {"available": False, "detail": result, "items": []}

    def positions(self) -> dict[str, Any]:
        ok, result = self._rpc("positions")
        return result if ok else {"available": False, "detail": result, "items": []}

    def history_orders(self, date_from: str, date_to: str) -> dict[str, Any]:
        ok, result = self._rpc("history_orders", date_from, date_to)
        return result if ok else {"available": False, "detail": result, "items": []}

    def history_deals(self, date_from: str, date_to: str) -> dict[str, Any]:
        ok, result = self._rpc("history_deals", date_from, date_to)
        return result if ok else {"available": False, "detail": result, "items": []}

    def history_order_by_ticket(self, ticket: int) -> dict[str, Any]:
        ok, result = self._rpc("history_order_by_ticket", ticket)
        return result if ok else {"available": False, "detail": result, "items": []}

    def history_deals_by_position(self, position_ticket: int) -> dict[str, Any]:
        ok, result = self._rpc("history_deals_by_position", position_ticket)
        return result if ok else {"available": False, "detail": result, "items": []}

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        ok, result = self._rpc("submit_order", order)
        return result if ok else {"ok": False, "unknown": True, "no_retry": True,
                                  "position_may_remain": True, "detail": result}

    def set_emergency_action(self, action: dict[str, Any]) -> None:
        ok, _result = self._rpc("set_emergency_action", action)
        if not ok:
            self.emergency_action = dict(action)

    def update_emergency_action(self, **updates: Any) -> None:
        ok, _result = self._rpc("update_emergency_action", **updates)
        if not ok:
            self.emergency_action = {**self.emergency_action, **updates}

    def __getattr__(self, name: str):
        if name not in _REMOTE_METHODS:
            raise AttributeError(name)

        def call(*args, **kwargs):
            ok, result = self._rpc(name, *args, **kwargs)
            if ok:
                return result
            if name in {"available_symbols", "market_watch_symbols"}:
                return []
            if name == "market_watch_catalog":
                return {"available": False, "source": "MT5 Market Watch", "count": 0,
                        "items": [], "detail": result}
            if name in {"positions", "orders", "history_orders", "history_deals"}:
                return {"available": False, "detail": result, "items": []}
            if name == "validate_market_symbols":
                return {"available": False, "valid": False, "invalid": [], "detail": result}
            if name == "economic_calendar":
                return {"status": "unavailable", "events": [], "detail": result}
            if name in {"arm_order_engine"}:
                return False
            if name == "disarm_order_engine":
                return None
            failed = {"ok": False, "unknown": True, "detail": result}
            if name in _TRADE_ACTION_METHODS:
                failed.update(no_retry=True, position_may_remain=True)
            return failed
        return call

    def shutdown(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        if self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=max(1, self._heartbeat_interval + 0.1))
        with self._rpc_lock:
            process = self._process
            if process is not None and process.is_alive() and self._connection is not None:
                self._request_id += 1
                try:
                    self._connection.send((self._request_id, "__shutdown__", (), {}))
                    if self._connection.poll(min(self._rpc_timeout, 1)):
                        self._connection.recv()
                except (EOFError, OSError, BrokenPipeError):
                    pass
                process.join(timeout=1)
            if process is not None and process.is_alive():
                process.terminate()
                process.join(timeout=1)
            self._close_transport()
            self._lifecycle = ConnectorLifecycle.DISCONNECTED
