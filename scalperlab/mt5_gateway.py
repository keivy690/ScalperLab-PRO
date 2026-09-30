from __future__ import annotations

from .position_sizing import size_order, valid_volume
from .risk_settings import validate_policy
import math

import importlib
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from .bar_time import normalize_bar_times

from .mt5_calendar_bridge import calendar_context_for_symbol, read_calendar_export, read_clock_export
from .mt5_time import (MAX_FUTURE_TIME_SKEW_SECONDS, MT5_MAX_CLOSED_BAR_AGE_SECONDS,
                       MT5TimeError, normalize_tick_time)


def _terminal_serialized(method):
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped


class MT5Gateway:
    """MT5 data gateway and explicitly armed, risk-limited order execution."""

    def __init__(self, mt5_module=None, *, terminal_id: str = "default",
                 terminal_path: str | None = None,
                 symbol_mappings: dict[str, str] | None = None) -> None:
        self._mt5 = mt5_module
        self.terminal_id = terminal_id
        self.terminal_path = terminal_path
        self.symbol_mappings = {key.upper(): value for key, value in (symbol_mappings or {}).items()}
        self._lock = threading.RLock()
        self._trade_lock = threading.RLock()
        self._initialized = False
        self._next_connect_attempt = 0.0
        self.demo_armed = False
        self._demo_armed_account_fingerprint: str | None = None
        self.strategy_engine_armed = False
        self.analyst_engine_armed = False
        self._engine_armed_mode: str | None = None
        self._engine_armed_fingerprint: str | None = None
        self.real_close_armed = False
        self._real_close_account_fingerprint: str | None = None
        self.last_error: str | None = None
        self.emergency_action: dict[str, Any] = {
            "status": "idle", "detail": "Nenhuma parada de emergência executada nesta sessão.",
            "updated_at": None, "remaining_count": None, "reconciled": False,
        }

    def _module(self):
        if self._mt5 is not None:
            return self._mt5
        try:
            self._mt5 = importlib.import_module("MetaTrader5")
        except ImportError:
            self.last_error = "Pacote MetaTrader5 não instalado neste Python."
            return None
        return self._mt5

    def arm_order_engine(self, engine: str, mode: str = "DEMO", fingerprint: str | None = None) -> bool:
        """Atomically arm one order engine for one explicitly identified account."""
        if engine not in {"strategy", "analyst"} or mode not in {"DEMO", "REAL"} or not fingerprint:
            return False
        with self._trade_lock, self._lock:
            other_armed = self.analyst_engine_armed if engine == "strategy" else self.strategy_engine_armed
            if other_armed or (self._engine_armed_mode and
                               (self._engine_armed_mode != mode or self._engine_armed_fingerprint != fingerprint)):
                return False
            self._engine_armed_mode = mode
            self._engine_armed_fingerprint = fingerprint
            if engine == "strategy":
                self.strategy_engine_armed = True
            else:
                self.analyst_engine_armed = True
            return True

    def disarm_order_engine(self, engine: str) -> None:
        with self._trade_lock, self._lock:
            if engine == "strategy":
                self.strategy_engine_armed = False
            elif engine == "analyst":
                self.analyst_engine_armed = False
            if not self.strategy_engine_armed and not self.analyst_engine_armed:
                self._engine_armed_mode = None
                self._engine_armed_fingerprint = None

    def set_emergency_action(self, action: dict[str, Any]) -> None:
        with self._lock:
            self.emergency_action = dict(action)

    def update_emergency_action(self, **updates: Any) -> None:
        with self._lock:
            self.emergency_action = {**self.emergency_action, **updates}

    def _connect(self):
        with self._lock:
            mt5 = self._module()
            if mt5 is None:
                return None
            try:
                if self._initialized:
                    terminal = mt5.terminal_info()
                    if terminal is not None and terminal.connected:
                        self.last_error = None
                        return mt5
                    if time.monotonic() < self._next_connect_attempt:
                        return mt5
                    try:
                        mt5.shutdown()
                    except Exception:
                        pass
                    self._initialized = False
                elif time.monotonic() < self._next_connect_attempt:
                    return None
                if not self._initialized:
                    try:
                        options = {"timeout": 5_000}
                        if self.terminal_path:
                            options["path"] = self.terminal_path
                        connected = mt5.initialize(**options)
                    except TypeError:  # narrow support for simple connector fakes
                        connected = mt5.initialize()
                    if not connected:
                        self._next_connect_attempt = time.monotonic() + 15
                        self.last_error = f"Terminal MT5 indisponível ({mt5.last_error()})."
                        return None
                    self._initialized = True
                    self._next_connect_attempt = 0.0
                self.last_error = None
                return mt5
            except Exception as exc:  # native extension/terminal errors are external to the app
                self._initialized = False
                self._next_connect_attempt = time.monotonic() + 15
                self.last_error = f"Falha ao consultar o terminal MT5: {type(exc).__name__}."
                return None

    def shutdown(self) -> None:
        """Release the Python connector cleanly when the desktop application exits."""
        with self._lock:
            if self._initialized and self._mt5 is not None:
                try:
                    self._mt5.shutdown()
                except Exception:
                    pass
            self._initialized = False
            self.demo_armed = False
            self._demo_armed_account_fingerprint = None
            self.real_close_armed = False
            self._real_close_account_fingerprint = None
            self.strategy_engine_armed = False
            self.analyst_engine_armed = False
            self._engine_armed_mode = self._engine_armed_fingerprint = None

    def resolve_broker_symbol(self, symbol: str) -> str:
        """Map an internal symbol ID to its exact name in this terminal."""
        return self.symbol_mappings.get(symbol.upper(), symbol)

    def available_symbols(self):
        """Return the complete broker catalog, independent of Market Watch visibility."""
        from .trading.models import Symbol
        mt5 = self._connect()
        if mt5 is None:
            return []
        rows = mt5.symbols_get()
        if rows is None:
            return []
        reverse = {broker: canonical for canonical, broker in self.symbol_mappings.items()}
        return [Symbol.from_broker_info(row, reverse.get(str(getattr(row, "name", ""))))
                for row in rows if getattr(row, "name", None)]

    def market_watch_symbols(self):
        """Return only symbols currently visible in this terminal's Market Watch."""
        return [symbol for symbol in self.available_symbols() if symbol.visible]

    def market_watch_catalog(self) -> dict[str, Any]:
        """Return a UI-ready Market Watch catalog while preserving MT5 failure details."""
        from .trading.models import Symbol

        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "source": "MT5 Market Watch", "count": 0,
                    "items": [], "detail": self.last_error or "Conector MT5 indisponível."}
        try:
            rows = mt5.symbols_get()
        except Exception as exc:
            return {"available": False, "source": "MT5 Market Watch", "count": 0,
                    "items": [], "detail": f"Falha ao consultar símbolos do MT5 ({type(exc).__name__})."}
        if rows is None:
            return {"available": False, "source": "MT5 Market Watch", "count": 0,
                    "items": [], "detail": f"O MT5 não retornou o catálogo ({mt5.last_error()})."}
        reverse = {broker: canonical for canonical, broker in self.symbol_mappings.items()}
        items = [Symbol.from_broker_info(row, reverse.get(str(getattr(row, "name", ""))))
                 for row in rows if getattr(row, "name", None) and getattr(row, "visible", False)]
        items.sort(key=lambda item: item.broker_symbol.casefold())
        return {"available": True, "source": "MT5 Market Watch", "count": len(items),
                "items": [item.to_dict() for item in items], "detail": None}

    def terminal_state(self) -> dict[str, Any]:
        state = self.state()
        return {"terminal_id": self.terminal_id, "connected": state["connected"],
                "status": state["status"], "detail": state.get("detail"),
                "terminal": state.get("terminal")}

    def account_state(self) -> dict[str, Any]:
        return self.state().get("account") or {}

    def tick(self, broker_symbol: str) -> dict[str, Any]:
        return self.current_tick(self.resolve_broker_symbol(broker_symbol))

    def rates(self, broker_symbol: str, timeframe: str, count: int) -> dict[str, Any]:
        return self.strategy_market_data(self.resolve_broker_symbol(broker_symbol), count, timeframe)

    def orders(self) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "detail": self.last_error, "items": []}
        try:
            rows = mt5.orders_get()
            if rows is None:
                return {"available": False, "detail": f"Consulta de ordens falhou ({mt5.last_error()}).",
                        "items": []}
            return {"available": True, "detail": None,
                    "items": [{"ticket": int(row.ticket), "symbol": str(row.symbol),
                               "type": int(row.type), "volume_current": float(row.volume_current),
                               "price_open": float(row.price_open), "sl": float(row.sl),
                               "tp": float(row.tp), "time_setup": int(row.time_setup)} for row in rows]}
        except Exception as exc:
            return {"available": False, "detail": f"Falha ao consultar ordens ({type(exc).__name__}).",
                    "items": []}

    @staticmethod
    def _history_bounds(date_from: str, date_to: str) -> tuple[datetime, datetime]:
        start = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
        end = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        start = start.replace(tzinfo=timezone.utc) if start.tzinfo is None else start.astimezone(timezone.utc)
        end = end.replace(tzinfo=timezone.utc) if end.tzinfo is None else end.astimezone(timezone.utc)
        if start >= end or end - start > timedelta(days=31):
            raise ValueError("Intervalo de histórico inválido; máximo permitido: 31 dias.")
        return start, end

    @_terminal_serialized
    def history_orders(self, date_from: str, date_to: str) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "detail": self.last_error, "items": []}
        try:
            start, end = self._history_bounds(date_from, date_to)
            rows = mt5.history_orders_get(start, end)
            if rows is None:
                return {"available": False, "detail": f"Histórico de ordens indisponível ({mt5.last_error()}).",
                        "items": []}
            fields = ("ticket", "time_setup", "time_setup_msc", "time_done", "time_done_msc",
                      "type", "state", "magic", "position_id", "symbol", "volume_initial",
                      "volume_current", "price_open", "price_current", "sl", "tp", "comment")
            return {"available": True, "detail": None,
                    "items": [{field: getattr(row, field) for field in fields
                               if hasattr(row, field)} for row in rows]}
        except Exception as exc:
            return {"available": False, "detail": f"Falha no histórico de ordens ({type(exc).__name__}).",
                    "items": []}

    @_terminal_serialized
    def history_deals(self, date_from: str, date_to: str) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "detail": self.last_error, "items": []}
        try:
            start, end = self._history_bounds(date_from, date_to)
            rows = mt5.history_deals_get(start, end)
            if rows is None:
                return {"available": False, "detail": f"Histórico de negócios indisponível ({mt5.last_error()}).",
                        "items": []}
            fields = ("ticket", "order", "time", "time_msc", "type", "entry", "magic",
                      "position_id", "reason", "volume", "price", "commission", "swap",
                      "profit", "fee", "symbol", "comment")
            return {"available": True, "detail": None,
                    "items": [{field: getattr(row, field) for field in fields
                               if hasattr(row, field)} for row in rows]}
        except Exception as exc:
            return {"available": False, "detail": f"Falha no histórico de negócios ({type(exc).__name__}).",
                    "items": []}

    @_terminal_serialized
    def history_order_by_ticket(self, ticket: int) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "detail": self.last_error, "items": []}
        try:
            rows = mt5.history_orders_get(ticket=int(ticket))
            if rows is None:
                return {"available": False,
                        "detail": f"Consulta da ordem histórica {ticket} falhou ({mt5.last_error()}).",
                        "items": []}
            fields = ("ticket", "time_setup", "time_setup_msc", "time_done", "time_done_msc",
                      "type", "state", "magic", "position_id", "symbol", "volume_initial",
                      "volume_current", "price_open", "price_current", "sl", "tp", "comment")
            return {"available": True, "detail": None,
                    "items": [{field: getattr(row, field) for field in fields
                               if hasattr(row, field)} for row in rows]}
        except Exception as exc:
            return {"available": False,
                    "detail": f"Falha na consulta da ordem histórica ({type(exc).__name__}).",
                    "items": []}

    @_terminal_serialized
    def history_deals_by_position(self, position_ticket: int) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "detail": self.last_error, "items": []}
        try:
            rows = mt5.history_deals_get(position=int(position_ticket))
            if rows is None:
                return {"available": False,
                        "detail": f"Consulta de negócios da posição {position_ticket} falhou ({mt5.last_error()}).",
                        "items": []}
            fields = ("ticket", "order", "time", "time_msc", "type", "entry", "magic",
                      "position_id", "reason", "volume", "price", "commission", "swap",
                      "profit", "fee", "symbol", "comment")
            return {"available": True, "detail": None,
                    "items": [{field: getattr(row, field) for field in fields
                               if hasattr(row, field)} for row in rows]}
        except Exception as exc:
            return {"available": False,
                    "detail": f"Falha na consulta de negócios da posição ({type(exc).__name__}).",
                    "items": []}

    @staticmethod
    def _correlated_comment(comment: str, correlation_id: str | None) -> str:
        if not correlation_id:
            return comment[:29]
        marker = f"SC{correlation_id.replace('-', '')[:10]}"
        # This MT5 build accepts at most 29 characters in order_check comments.
        return f"{marker} {comment}"[:29]

    def submit_order(self, order: dict[str, Any]) -> dict[str, Any]:
        """Submit only through the existing explicitly armed, risk-checked order paths."""
        engine = order.get("engine")
        mode = str(order.get("mode", "")).lower()
        side = str(order.get("side", "")).upper()
        if mode not in {"demo", "real"}:
            return {"ok": False, "detail": "Modo de ordem não suportado."}
        method_name = f"send_{'real' if mode == 'real' else 'demo'}_{engine}_order"
        sender = getattr(self, method_name, None) if engine in {"strategy", "analyst"} else None
        required = ("symbol", "volume", "stop", "target", "account_fingerprint", "risk_cash")
        if sender is None or side not in {"BUY", "SELL"} or any(key not in order for key in required):
            return {"ok": False, "detail": "Intenção de ordem incompleta ou sem fluxo de segurança suportado."}
        args = (self.resolve_broker_symbol(str(order["symbol"])), side,
                float(order["volume"]), float(order["stop"]), float(order["target"]))
        if engine == "strategy":
            return sender(*args, order.get("strategy_id", 1),
                          str(order["account_fingerprint"]), float(order["risk_cash"]),
                          correlation_id=order.get("correlation_id"))
        return sender(*args, str(order["account_fingerprint"]), float(order["risk_cash"]),
                      correlation_id=order.get("correlation_id"))

    @_terminal_serialized
    def state(self) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"connected": False, "status": "indisponível", "detail": self.last_error,
                    "account": None, "terminal": None, "demo_armed": self.demo_armed,
                    "real_trading": "disponivel_com_confirmacao", "emergency_action": dict(self.emergency_action)}
        try:
            account = mt5.account_info()
            terminal = mt5.terminal_info()
            if account is None:
                self.demo_armed = False
                self._demo_armed_account_fingerprint = None
                return {"connected": False, "status": "sem conta", "detail": str(mt5.last_error()),
                        "account": None, "terminal": None, "demo_armed": self.demo_armed,
                        "real_trading": "disponivel_com_confirmacao", "emergency_action": dict(self.emergency_action)}
            mode = "DEMO" if account.trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0) else (
                "CONTEST" if account.trade_mode == getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", 1) else "REAL")
            fingerprint = f"{account.login}@{account.server}"
            if self.demo_armed and (not terminal or not terminal.connected or mode != "DEMO"
                                     or fingerprint != self._demo_armed_account_fingerprint):
                self.demo_armed = False
                self._demo_armed_account_fingerprint = None
            if self.real_close_armed and (not terminal or not terminal.connected or mode != "REAL"
                                          or fingerprint != self._real_close_account_fingerprint):
                self.real_close_armed = False
                self._real_close_account_fingerprint = None
            if self._engine_armed_mode and (not terminal or not terminal.connected
                    or mode != self._engine_armed_mode or fingerprint != self._engine_armed_fingerprint):
                self.strategy_engine_armed = self.analyst_engine_armed = False
                self._engine_armed_mode = self._engine_armed_fingerprint = None
            return {
                "connected": bool(terminal and terminal.connected), "status": "conectado" if terminal and terminal.connected else "desconectado",
                "clock_bridge": read_clock_export(
                    getattr(terminal, "commondata_path", None), login=str(account.login),
                    server=str(account.server), terminal_data_path=getattr(terminal, "data_path", None)),
                "detail": None if terminal and terminal.connected else "O terminal está inicializado, mas não conectado ao servidor.",
                "account": {"login": str(account.login), "server": str(account.server), "company": str(account.company),
                            "currency": str(account.currency), "balance": float(account.balance),
                            "equity": float(account.equity), "profit": float(account.profit), "mode": mode,
                            "leverage": int(account.leverage),
                            "margin": float(getattr(account, "margin", 0.0)),
                            "margin_free": float(getattr(account, "margin_free", 0.0)),
                            "margin_level": float(getattr(account, "margin_level", 0.0)),
                            "trade_allowed": bool(getattr(account, "trade_allowed", False)),
                            "trade_expert": bool(getattr(account, "trade_expert", False)),
                            "limit_orders": int(getattr(account, "limit_orders", 0)),
                            "fifo_close": bool(getattr(account, "fifo_close", False)),
                            "server_time": int(getattr(account, "server_time", 0))},
                "terminal": {"name": str(terminal.name), "build": int(terminal.build),
                             "trade_allowed": bool(terminal.trade_allowed)} if terminal else None,
                "demo_armed": self.demo_armed, "real_close_armed": self.real_close_armed,
                "real_trading": "disponivel_com_confirmacao",
                "emergency_action": dict(self.emergency_action),
            }
        except Exception as exc:
            self.last_error = f"Falha ao ler estado do MT5: {type(exc).__name__}."
            return {"connected": False, "status": "erro", "detail": self.last_error,
                    "account": None, "terminal": None, "demo_armed": self.demo_armed,
                    "real_trading": "disponivel_com_confirmacao", "emergency_action": dict(self.emergency_action)}

    @_terminal_serialized
    def positions(self) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "detail": self.last_error, "items": []}
        try:
            rows = mt5.positions_get()
            if rows is None:
                return {"available": False, "detail": f"Consulta de posições falhou ({mt5.last_error()}).", "items": []}
            items = []
            for position in rows:
                items.append({"ticket": int(position.ticket), "symbol": str(position.symbol),
                              "type": "BUY" if position.type == mt5.POSITION_TYPE_BUY else "SELL",
                              "volume": float(position.volume), "price_open": float(position.price_open),
                              "price_current": float(position.price_current), "sl": float(position.sl),
                              "tp": float(position.tp), "profit": float(position.profit),
                              "time": int(position.time), "magic": int(position.magic),
                              "comment": str(position.comment)[:120]})
            return {"available": True, "detail": None, "items": items}
        except Exception as exc:
            return {"available": False, "detail": f"Falha ao ler posições ({type(exc).__name__}).", "items": []}

    @_terminal_serialized
    def validate_market_symbols(self, requested: list[str]) -> dict[str, Any]:
        """Resolve configured names against this broker's visible Market Watch symbols."""
        mt5 = self._connect()
        if mt5 is None:
            return {"available": False, "valid": False, "invalid": [],
                    "detail": self.last_error or "MT5 indisponível."}
        try:
            rows = mt5.symbols_get()
            if rows is None:
                return {"available": False, "valid": False, "invalid": [],
                        "detail": f"Não foi possível listar os símbolos do MT5 ({mt5.last_error()})."}
            visible = [row for row in rows if bool(getattr(row, "visible", True))]
            visible_names = {str(getattr(row, "name", "")) for row in visible
                             if getattr(row, "name", None)}
            requested = [self.resolve_broker_symbol(name) for name in requested]
            invalid = []
            for name in requested:
                if name in visible_names:
                    continue
                normalized = re.sub(r"[^A-Z0-9]", "", name.upper())
                matches = [candidate for candidate in visible_names
                           if re.sub(r"[^A-Z0-9]", "", candidate.upper()).startswith(normalized)
                           or normalized.startswith(re.sub(r"[^A-Z0-9]", "", candidate.upper()))]
                invalid.append({"requested": name, "suggestions": matches[:5]})
            return {"available": True, "valid": not invalid, "invalid": invalid,
                    "detail": None if not invalid else "Use os nomes exatos dos ativos visíveis no Market Watch."}
        except Exception as exc:
            return {"available": False, "valid": False, "invalid": [],
                    "detail": f"Falha ao validar símbolos ({type(exc).__name__})."}

    @_terminal_serialized
    def economic_calendar(self, symbol_name: str) -> dict[str, Any]:
        """Read the local read-only MQL5 calendar snapshot, tied to the connected account."""
        symbol_name = self.resolve_broker_symbol(symbol_name)
        mt5 = self._connect()
        if mt5 is None:
            return {"status": "unavailable", "events": [], "detail": self.last_error or "MT5 indisponível."}
        try:
            account = mt5.account_info()
            terminal = mt5.terminal_info()
            symbol = mt5.symbol_info(symbol_name)
            if not account or not terminal or not terminal.connected or not symbol:
                return {"status": "unavailable", "events": [],
                        "detail": "Conta, terminal ou especificação do ativo indisponível."}
            raw = read_calendar_export(getattr(terminal, "commondata_path", ""),
                                       login=str(account.login), server=str(account.server))
            currencies = {str(getattr(symbol, "currency_base", "")).upper(),
                          str(getattr(symbol, "currency_profit", "")).upper()}
            currencies.discard("")
            return calendar_context_for_symbol(raw, currencies)
        except Exception as exc:
            return {"status": "unavailable", "events": [],
                    "detail": f"Falha segura ao consultar calendário ({type(exc).__name__})."}

    @_terminal_serialized
    def strategy_market_data(self, symbol_name: str, count: int = 2400,
                             timeframe: str = "M1", *, require_fresh: bool = True) -> dict[str, Any]:
        """Read closed bars and broker symbol contract details; never sends an order."""
        timeframe = str(timeframe).upper()
        symbol_name = self.resolve_broker_symbol(symbol_name)
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "detail": self.last_error or "MT5 indisponível."}
        try:
            timeframe_id = getattr(mt5, f"TIMEFRAME_{timeframe}", None)
            if timeframe_id is None:
                return {"ok": False, "detail": f"Timeframe MT5 não suportado: {timeframe}."}
            symbol = mt5.symbol_info(symbol_name)
            if symbol is None:
                return {"ok": False, "detail": f"Símbolo {symbol_name} não encontrado no MT5."}
            if not symbol.visible and not mt5.symbol_select(symbol_name, True):
                return {"ok": False, "detail": f"Não foi possível habilitar {symbol_name} no Market Watch."}
            rates = mt5.copy_rates_from_pos(symbol_name, timeframe_id, 1, max(1, min(int(count), 20000)))
            if rates is None:
                return {"ok": False, "detail": f"Histórico {timeframe} indisponível ({mt5.last_error()})."}
            def rate_value(row, key, default=0):
                try:
                    return row[key]
                except (KeyError, IndexError, TypeError, ValueError):
                    return default

            bars = [{"time": int(rate_value(row, "time")), "open": float(rate_value(row, "open")),
                     "high": float(rate_value(row, "high")), "low": float(rate_value(row, "low")),
                     "close": float(rate_value(row, "close")),
                     "tick_volume": int(rate_value(row, "tick_volume")),
                     "spread": int(rate_value(row, "spread")),
                     "real_volume": int(rate_value(row, "real_volume"))}
                    for row in rates]
            tick = self.current_tick(symbol_name)
            if not tick.get("ok"):
                return tick
            tick_time = tick["time_normalization"]
            offset = tick_time["server_utc_offset_seconds"]
            # The forming M1 bar identifies the rate stream's encoding separately
            # from tick normalization. Never infer it from an old closed candle.
            forming = mt5.copy_rates_from_pos(symbol_name, mt5.TIMEFRAME_M1, 0, 1)
            if forming is None or len(forming) != 1:
                return {"ok": False, "code": "bar_time_unverified",
                        "detail": "Barra M1 em formação indisponível para validar o horário do histórico."}
            bars, bar_time = normalize_bar_times(
                bars, m1_open=int(rate_value(forming[0], "time")), tick_utc=tick["time"],
                server_offset=offset, timeframe=timeframe, allow_recent_tail=require_fresh)
            now_epoch = time.time()
            latest_bar_age = now_epoch - bars[-1]["time"] if bars else None
            max_closed_bar_age = MT5_MAX_CLOSED_BAR_AGE_SECONDS.get(timeframe)
            if not bars or bars[-1]["time"] > now_epoch + MAX_FUTURE_TIME_SKEW_SECONDS:
                return {"ok": False,
                        "detail": "Histórico MT5 permanece no futuro após a normalização UTC."}
            if max_closed_bar_age is None:
                return {"ok": False, "detail": f"Timeframe MT5 sem regra de frescor: {timeframe}."}
            if require_fresh and (latest_bar_age is None or latest_bar_age > max_closed_bar_age):
                return {"ok": False,
                        "detail": "Último candle fechado desatualizado; análise bloqueada."}
            return {"ok": True, "symbol": symbol.name, "bars": bars,
                    "time_normalization": {
                        "basis": "UTC",
                        "source": "rates_m1_evidence; tick_mql5_clock_snapshot",
                        **bar_time,
                        "server_utc_offset_seconds": offset,
                        "tick_age_seconds": tick_time["age_seconds"],
                        "calibration_residual_seconds": tick_time["calibration_residual_seconds"],
                        "clock_reference": tick_time["clock_reference"],
                        "last_closed_bar_age_seconds": round(latest_bar_age, 3),
                    },
                    "contract": {"digits": int(symbol.digits), "point": float(symbol.point),
                                 "trade_tick_size": float(getattr(symbol, "trade_tick_size", 0.0)),
                                 "trade_tick_value_profit": float(getattr(symbol, "trade_tick_value_profit", 0.0)),
                                 "trade_tick_value_loss": float(getattr(symbol, "trade_tick_value_loss", 0.0)),
                                 "trade_contract_size": float(getattr(symbol, "trade_contract_size", 0.0)),
                                 "currency_base": str(getattr(symbol, "currency_base", "")),
                                 "currency_profit": str(getattr(symbol, "currency_profit", "")),
                                 "currency_margin": str(getattr(symbol, "currency_margin", "")),
                                 "country": str(getattr(symbol, "country", "")),
                                 "sector": str(getattr(symbol, "sector_name", "")),
                                 "swap_long": float(getattr(symbol, "swap_long", 0.0)),
                                 "swap_short": float(getattr(symbol, "swap_short", 0.0)),
                                 "swap_mode": int(getattr(symbol, "swap_mode", 0)),
                                 "chart_mode": int(getattr(symbol, "chart_mode", 0)),
                                 "swap_rollover3days": int(getattr(symbol, "swap_rollover3days", 0)),
                                 "trade_mode": int(symbol.trade_mode),
                                 "volume_min": float(symbol.volume_min),
                                 "volume_max": float(symbol.volume_max),
                                 "volume_step": float(symbol.volume_step),
                                 "trade_stops_level": int(symbol.trade_stops_level),
                                 "filling_mode": int(symbol.filling_mode),
                                 "trade_exemode": int(symbol.trade_exemode)}}
        except MT5TimeError as exc:
            return {"ok": False, "detail": str(exc), "code": exc.code}
        except Exception as exc:
            return {"ok": False, "detail": f"Falha ao consultar barras/contrato ({type(exc).__name__})."}

    def historical_market_data(self, symbol_name: str, count: int = 1200,
                               timeframe: str = "M15") -> dict[str, Any]:
        """Read closed historical bars for offline replay; this method never sends orders."""
        return self.strategy_market_data(symbol_name, count, timeframe, require_fresh=False)

    @_terminal_serialized
    def sr_raw_time_sample(self, symbol_name: str, count: int = 2) -> dict[str, Any]:
        """Read raw MT5 rate timestamps for S/R research, without changing the trading path."""
        if not 1 <= int(count) <= 1000:
            return {"ok": False, "code": "invalid_count",
                    "detail": "Use de 1 a 1000 barras por período."}
        symbol_name = self.resolve_broker_symbol(symbol_name)
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "code": "terminal_unavailable",
                    "detail": self.last_error or "MT5 indisponível."}
        try:
            before = mt5.account_info()
            terminal = mt5.terminal_info()
            symbol = mt5.symbol_info(symbol_name)
            if (not before or not terminal or not getattr(terminal, "connected", False)
                    or not symbol or not symbol.visible or symbol.name != symbol_name):
                return {"ok": False, "code": "identity_or_symbol_unavailable",
                        "detail": "Conta, terminal ou símbolo exato do Market Watch indisponível."}
            tick = self.current_tick(symbol_name)
            if not tick.get("ok"):
                return tick
            frames = {}
            for frame in ("M1", "M5", "M15", "H1"):
                frame_id = getattr(mt5, f"TIMEFRAME_{frame}")
                rates = mt5.copy_rates_from_pos(symbol_name, frame_id, 0, int(count) + 1)
                if rates is None or len(rates) < 2:
                    return {"ok": False, "code": "raw_rates_unavailable",
                            "detail": f"Barras brutas {frame} indisponíveis."}
                rows = [{"time": int(row["time"]), "open": float(row["open"]),
                         "high": float(row["high"]), "low": float(row["low"]),
                         "close": float(row["close"]),
                         "tick_volume": int(row["tick_volume"]),
                         "spread": int(row["spread"]),
                         "real_volume": int(row["real_volume"])} for row in rates]
                if any(a["time"] >= b["time"]
                       for a, b in zip(rows, rows[1:], strict=False)):
                    return {"ok": False, "code": "raw_rates_sequence",
                            "detail": f"Barras brutas {frame} duplicadas ou fora de ordem."}
                frames[frame] = {"closed": rows[:-1], "forming": rows[-1]}
            after = mt5.account_info()
            after_terminal = mt5.terminal_info()
            if (not after or not after_terminal or not getattr(after_terminal, "connected", False)
                    or (before.login, before.server) != (after.login, after.server)
                    or getattr(terminal, "data_path", None)
                    != getattr(after_terminal, "data_path", None)):
                return {"ok": False, "code": "identity_changed",
                        "detail": "Conta ou terminal mudou durante a amostra; dados descartados."}
            return {"ok": True, "symbol": symbol_name, "terminal_id": self.terminal_id,
                    "account": {"login": str(before.login), "server": str(before.server)},
                    "terminal": {"data_path": str(getattr(terminal, "data_path", "")),
                                 "build": int(getattr(terminal, "build", 0))},
                    "captured_utc": int(time.time()), "tick": tick, "frames": frames}
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            return {"ok": False, "code": "raw_sample_failed",
                    "detail": f"Falha na amostra bruta: {type(exc).__name__}."}

    @_terminal_serialized
    def current_tick(self, symbol_name: str) -> dict[str, Any]:
        symbol_name = self.resolve_broker_symbol(symbol_name)
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "detail": self.last_error or "MT5 indisponível."}
        diagnostics = {"symbol": symbol_name, "source": "mql5_clock_snapshot"}
        try:
            terminal = mt5.terminal_info()
            account = mt5.account_info()
            if not terminal or not account or not getattr(terminal, "connected", False):
                return {"ok": False, "detail": "Terminal/conta MT5 indisponível.",
                        "code": "clock_unavailable", "time_normalization": diagnostics}
            reference = read_clock_export(
                getattr(terminal, "commondata_path", None),
                login=str(account.login), server=str(account.server),
                terminal_data_path=getattr(terminal, "data_path", None))
            diagnostics["clock_reference"] = reference
            if not reference["ok"]:
                return {"ok": False, "detail": reference["detail"],
                        "code": reference["code"], "severity": reference["severity"],
                        "time_normalization": diagnostics}
            tick = mt5.symbol_info_tick(symbol_name)
            if tick is None or not float(tick.bid) > 0 or not float(tick.ask) > 0:
                return {"ok": False, "detail": "Sem cotação válida para o símbolo."}
            diagnostics.update(raw_time=getattr(tick, "time", 0),
                               raw_time_msc=getattr(tick, "time_msc", None),
                               server_utc_offset_seconds=reference["server_utc_offset_seconds"])
            after = mt5.account_info()
            after_terminal = mt5.terminal_info()
            if (not after or not after_terminal
                    or not getattr(after_terminal, "connected", False)
                    or (account.login, account.server) != (after.login, after.server)
                    or getattr(terminal, "data_path", None) != getattr(after_terminal, "data_path", None)):
                return {"ok": False, "code": "clock_identity", "severity": "hard",
                        "detail": "Conta ou terminal mudou durante a leitura do relógio.",
                        "time_normalization": diagnostics}
            normalized = normalize_tick_time(
                getattr(tick, "time", 0), getattr(tick, "time_msc", None),
                server_utc_offset_seconds=reference["server_utc_offset_seconds"])
            return {"ok": True, "bid": float(tick.bid), "ask": float(tick.ask),
                    "time": normalized.utc_time, "time_msc": normalized.utc_time_msc,
                    "time_normalization": {
                        **diagnostics, "basis": "UTC", "source": "mql5_clock_snapshot",
                        "server_utc_offset_seconds": normalized.server_utc_offset_seconds,
                        "age_seconds": round(normalized.age_seconds, 3),
                        "calibration_residual_seconds": round(
                            normalized.calibration_residual_seconds, 3),
                    }}
        except MT5TimeError as exc:
            return {"ok": False, "detail": str(exc), "code": exc.code,
                    "time_normalization": {**diagnostics, **exc.diagnostics}}
        except Exception as exc:
            return {"ok": False, "detail": f"Falha ao ler cotação ({type(exc).__name__})."}

    @_terminal_serialized
    def risk_volume(self, symbol_name: str, side: str, entry: float, stop: float,
                    risk_cash: float, hard_cap: float = 0.01, *, policy: dict | None = None) -> dict[str, Any]:
        symbol_name = self.resolve_broker_symbol(symbol_name)
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "detail": self.last_error or "MT5 indisponível."}
        try:
            symbol = mt5.symbol_info(symbol_name)
            if symbol is None:
                return {"ok": False, "detail": "Contrato do ativo indisponível."}
            return size_order(mt5, symbol, side, float(entry), float(stop), float(risk_cash),
                              policy or {"max_volume": hard_cap})
        except Exception as exc:
            return {"ok": False, "detail": f"Falha ao dimensionar posição ({type(exc).__name__})."}

    def send_demo_strategy_order(self, symbol_name: str, side: str, volume: float,
                                 stop: float, target: float, strategy_id: int,
                                 expected_account_fingerprint: str | None = None,
                                 risk_cash: float | None = None,
                                 correlation_id: str | None = None, risk_policy: dict | None = None) -> dict[str, Any]:
        """Single demo-only market request. Ambiguous results are never retried."""
        with self._trade_lock, self._lock:
            return self._send_account_order(
                symbol_name, side, volume, stop, target, strategy_id, expected_account_fingerprint,
                "strategy", risk_cash=risk_cash, correlation_id=correlation_id, risk_policy=risk_policy)

    def send_real_strategy_order(self, symbol_name: str, side: str, volume: float,
                                 stop: float, target: float, strategy_id: int,
                                 expected_account_fingerprint: str | None = None,
                                 risk_cash: float | None = None,
                                 correlation_id: str | None = None, risk_policy: dict | None = None) -> dict[str, Any]:
        with self._trade_lock, self._lock:
            return self._send_account_order(symbol_name, side, volume, stop, target,
                strategy_id, expected_account_fingerprint, "strategy", risk_cash=risk_cash,
                mode="REAL", correlation_id=correlation_id, risk_policy=risk_policy)

    def send_demo_analyst_order(self, symbol_name: str, side: str, volume: float,
                                stop: float, target: float,
                                expected_account_fingerprint: str | None = None,
                                risk_cash: float | None = None,
                                max_spread: float | None = None,
                                min_reward_risk: float | None = None,
                                correlation_id: str | None = None, risk_policy: dict | None = None) -> dict[str, Any]:
        """Independent DEMO-only order path for the market analyst; never retries ambiguous sends."""
        with self._trade_lock, self._lock:
            return self._send_account_order(
                symbol_name, side, volume, stop, target, 998, expected_account_fingerprint, "analyst",
                risk_cash=risk_cash, max_spread=max_spread, min_reward_risk=min_reward_risk,
                correlation_id=correlation_id, risk_policy=risk_policy)

    def send_real_analyst_order(self, symbol_name: str, side: str, volume: float,
                                stop: float, target: float,
                                expected_account_fingerprint: str | None = None,
                                risk_cash: float | None = None,
                                max_spread: float | None = None,
                                min_reward_risk: float | None = None,
                                correlation_id: str | None = None, risk_policy: dict | None = None) -> dict[str, Any]:
        with self._trade_lock, self._lock:
            return self._send_account_order(symbol_name, side, volume, stop, target, 998,
                expected_account_fingerprint, "analyst", risk_cash=risk_cash,
                max_spread=max_spread, min_reward_risk=min_reward_risk, mode="REAL",
                correlation_id=correlation_id, risk_policy=risk_policy)

    def _send_account_order(self, symbol_name: str, side: str, volume: float,
                                  stop: float, target: float, strategy_id: int,
                                  expected_account_fingerprint: str | None,
                                  engine: str = "strategy", risk_cash: float | None = None,
                                  max_spread: float | None = None,
                                  min_reward_risk: float | None = None,
                                  mode: str = "DEMO",
                                  correlation_id: str | None = None, risk_policy: dict | None = None) -> dict[str, Any]:
        symbol_name = self.resolve_broker_symbol(symbol_name)
        armed = self.analyst_engine_armed if engine == "analyst" else self.strategy_engine_armed
        if not armed or self._engine_armed_mode != mode:
            return {"ok": False, "blocked": True, "detail": "Motor de execução não está armado; nenhuma ordem enviada."}
        if not expected_account_fingerprint:
            return {"ok": False, "blocked": True, "detail": "Identidade da conta confirmada não foi informada; nenhuma ordem enviada."}
        state = self.state()
        account = state.get("account") or {}
        if not state.get("connected") or account.get("mode") != mode:
            return {"ok": False, "blocked": True, "detail": f"O motor foi armado para conta {mode}; nenhuma ordem enviada."}
        fingerprint = f"{account.get('login')}@{account.get('server')}"
        if fingerprint != expected_account_fingerprint or fingerprint != self._engine_armed_fingerprint:
            return {"ok": False, "blocked": True, "detail": "Login/servidor mudou desde a confirmação; ordem bloqueada até novo armamento."}
        if (not state.get("terminal", {}).get("trade_allowed")
                or not account.get("trade_allowed") or not account.get("trade_expert")):
            return {"ok": False, "detail": "Negociação não está habilitada no terminal MT5."}
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "detail": self.last_error or "MT5 indisponível."}
        try:
            symbol = mt5.symbol_info(symbol_name)
            tick = mt5.symbol_info_tick(symbol_name)
            if symbol is None or tick is None or not float(tick.bid) > 0 or not float(tick.ask) > 0:
                return {"ok": False, "detail": "Cotação ou contrato indisponível; nenhuma ordem enviada."}
            if symbol.trade_mode != getattr(mt5, "SYMBOL_TRADE_MODE_FULL", 4):
                return {"ok": False, "detail": "O símbolo não aceita negociação nos dois sentidos."}
            if max_spread is not None and float(tick.ask) - float(tick.bid) > max_spread:
                return {"ok": False, "detail": "Spread se alargou antes do envio; sinal descartado."}
            policy = validate_policy(risk_policy or {})
            if risk_policy is not None and (risk_cash is None or not math.isfinite(float(risk_cash)) or risk_cash <= 0):
                return {"ok": False, "detail": "Orçamento de risco inválido."}
            if (not valid_volume(float(volume), symbol) or volume > policy["max_volume"]
                    or (policy["sizing_mode"] == "fixed_lot" and abs(volume - policy["fixed_volume"]) > 1e-9)
                    or (float(getattr(symbol, "volume_limit", 0) or 0) > 0 and volume > symbol.volume_limit)):
                return {"ok": False, "detail": "Volume incompatível com o contrato ou o perfil de lote e risco."}
            positions = mt5.positions_get()
            if positions is None:
                return {"ok": False, "detail": "Não foi possível reconciliar posições abertas; envio cancelado."}
            if positions:
                return {"ok": False, "detail": "Já existe posição aberta na conta; o motor não abrirá outra."}
            active_orders = mt5.orders_get()
            if active_orders is None:
                return {"ok": False, "detail": "Não foi possível confirmar ordens pendentes; envio cancelado."}
            if active_orders:
                return {"ok": False, "detail": "Há ordem(ns) pendente(s) na conta; o motor não abrirá outra."}
            is_buy = side == "BUY"
            price = float(tick.ask if is_buy else tick.bid)
            digits = int(symbol.digits)
            stop, target = round(float(stop), digits), round(float(target), digits)
            if (is_buy and not stop < price < target) or (not is_buy and not target < price < stop):
                return {"ok": False, "detail": "A cotação mudou e invalida a relação entrada/stop/alvo; sinal descartado."}
            if min_reward_risk is not None:
                actual_reward_risk = ((target - price) / (price - stop) if is_buy
                                      else (price - target) / (stop - price))
                if actual_reward_risk < min_reward_risk:
                    return {"ok": False, "detail": "Movimento do preço reduziu a relação risco/retorno mínima; entrada cancelada."}
            if risk_cash is not None:
                calc_type = mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL
                loss = mt5.order_calc_profit(calc_type, symbol_name, float(volume), price, stop)
                if loss is None or not math.isfinite(float(loss)) or float(loss) >= 0 or abs(float(loss)) > risk_cash * 1.000001:
                    return {"ok": False, "detail": "Preço atual excederia o teto de risco calculado; ordem cancelada."}
            account_info = mt5.account_info()
            margin = mt5.order_calc_margin(mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                                           symbol_name, float(volume), price)
            if (account_info is None or margin is None or not math.isfinite(float(margin)) or float(margin) < 0
                    or not math.isfinite(float(getattr(account_info, "margin_free", 0.0)))
                    or float(margin) > float(getattr(account_info, "margin_free", 0.0)) * (1 - policy["margin_reserve_pct"] / 100)):
                return {"ok": False, "detail": "Margem insuficiente ou não calculável com a reserva configurada; ordem cancelada."}
            magic = 209222050 if engine == "analyst" else 209221050 + int(strategy_id % 1000)
            comment = "SL1 ANALYST" if engine == "analyst" else f"SL1 S{strategy_id}"[:31]
            request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol_name, "volume": float(volume),
                       "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
                       "sl": stop, "tp": target, "deviation": 20,
                       "magic": magic, "comment": comment, "type_time": mt5.ORDER_TIME_GTC,
                       "type_filling": self._filling(mt5, symbol)}
            request["comment"] = self._correlated_comment(comment, correlation_id)
            if int(getattr(symbol, "trade_exemode", -1)) != getattr(mt5, "SYMBOL_TRADE_EXECUTION_MARKET", 2):
                request["price"] = price
            check = mt5.order_check(request)
            if check is None or getattr(check, "retcode", None) not in {0, getattr(mt5, "TRADE_RETCODE_DONE", 10009)}:
                return {"ok": False, "detail": f"MT5 rejeitou a pré-verificação ({getattr(check, 'retcode', 'indisponível')}); nenhuma ordem enviada."}
            final_state = self.state()
            final_account = final_state.get("account") or {}
            final_fingerprint = f"{final_account.get('login')}@{final_account.get('server')}"
            if (not final_state.get("connected") or final_account.get("mode") != mode
                    or final_fingerprint != expected_account_fingerprint
                    or not final_state.get("terminal", {}).get("trade_allowed")
                    or not final_account.get("trade_allowed") or not final_account.get("trade_expert")):
                return {"ok": False, "blocked": True,
                        "detail": f"Conta, conexão ou permissão {mode} mudou antes do envio; ordem cancelada."}
            final_positions = mt5.positions_get()
            if final_positions is None or final_positions:
                return {"ok": False, "blocked": True,
                        "detail": "A posição aberta mudou durante a validação; ordem cancelada."}
            final_orders = mt5.orders_get()
            if final_orders is None or final_orders:
                return {"ok": False, "blocked": True,
                        "detail": "Ordens pendentes mudaram durante a validação; ordem cancelada."}
            try:
                result = mt5.order_send(request)
            except Exception as exc:
                return {"ok": False, "unknown": True, "no_retry": True,
                        "correlation_id": correlation_id,
                        "detail": f"Resultado do envio desconhecido ({type(exc).__name__}); não reenvie antes de conferir posições/histórico."}
            if result is None:
                return {"ok": False, "unknown": True, "no_retry": True,
                        "correlation_id": correlation_id,
                        "detail": f"MT5 não confirmou o envio ({mt5.last_error()}); não reenvie antes da reconciliação."}
            accepted = {getattr(mt5, "TRADE_RETCODE_DONE", 10009),
                        getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)}
            if result.retcode not in accepted:
                return {"ok": False, "retcode": int(result.retcode),
                        "correlation_id": correlation_id,
                        "detail": f"MT5 rejeitou a ordem (retcode {result.retcode}); sinal consumido até a próxima sessão."}
            after = mt5.positions_get(symbol=symbol_name)
            marker = f"SC{correlation_id.replace('-', '')[:10]}" if correlation_id else None
            matches = [p for p in (after or []) if int(p.magic) == magic and (
                str(p.comment).startswith(comment) or (marker and marker in str(p.comment)))]
            if after is None or len(matches) != 1:
                return {"ok": False, "unknown": True, "no_retry": True,
                        "correlation_id": correlation_id,
                        "detail": "Ordem aceita sem reconciliação inequívoca; não haverá repetição. Confira o MT5.",
                        "order": int(getattr(result, "order", 0)), "deal": int(getattr(result, "deal", 0))}
            position = matches[0]
            if not float(position.sl) or not float(position.tp):
                return {"ok": False, "unknown": True, "position_may_remain": True,
                        "correlation_id": correlation_id,
                        "detail": "Posição encontrada sem stop/alvo confirmados no servidor. Motor interrompido; verifique o MT5 manualmente.",
                        "ticket": int(position.ticket)}
            return {"ok": True, "correlation_id": correlation_id, "symbol": symbol_name,
                    "side": side, "requested_volume": float(volume),
                    "requested_price": price, "filled_volume": float(position.volume),
                    "filled_price": float(position.price_open), "retcode": int(result.retcode),
                    "ticket": int(position.ticket), "order": int(getattr(result, "order", 0)),
                    "deal": int(getattr(result, "deal", 0)), "volume": float(position.volume),
                    "price": float(position.price_open), "sl": float(position.sl), "tp": float(position.tp),
                    "reconciled": True,
                    "detail": f"Ordem {mode} confirmada com stop e alvo reconciliados no MT5."}
        except Exception as exc:
            return {"ok": False, "unknown": True, "detail": f"Falha durante envio/reconciliação ({type(exc).__name__}); não reenvie até conferir o terminal."}

    def arm_demo(self, confirmation: str) -> dict[str, Any]:
        with self._trade_lock, self._lock:
            return self._arm_demo(confirmation)

    def _arm_demo(self, confirmation: str) -> dict[str, Any]:
        if confirmation != "ATIVAR SOMENTE DEMO":
            return {"ok": False, "detail": "Confirmação incorreta. Nenhuma operação foi habilitada."}
        state = self.state()
        account = state.get("account") or {}
        if not state.get("connected") or not account:
            return {"ok": False, "detail": "Conecte uma conta no terminal antes de armar a execução demo."}
        if account.get("mode") != "DEMO":
            return {"ok": False, "detail": "Este armamento é exclusivo para fechamento DEMO."}
        if (not state.get("terminal", {}).get("trade_allowed")
                or not account.get("trade_allowed") or not account.get("trade_expert")):
            return {"ok": False, "detail": "O terminal está com negociação desabilitada."}
        self.demo_armed = True
        self._demo_armed_account_fingerprint = f"{account.get('login')}@{account.get('server')}"
        return {"ok": True, "detail": "Fechamento de posições em DEMO habilitado até o aplicativo ser encerrado."}

    def close_demo_position(self, ticket: int, confirmation: str,
                            expected_account_fingerprint: str | None = None,
                            correlation_id: str | None = None) -> dict[str, Any]:
        with self._trade_lock, self._lock:
            return self._close_demo_position(ticket, confirmation, expected_account_fingerprint,
                                             correlation_id)

    def arm_real_closing(self, confirmation: str) -> dict[str, Any]:
        if confirmation != "AUTORIZO FECHAMENTO EM CONTA REAL":
            return {"ok": False, "detail": "Confirmação incorreta; fechamento REAL permanece desarmado."}
        state = self.state()
        account = state.get("account") or {}
        if not state.get("connected") or account.get("mode") != "REAL":
            return {"ok": False, "detail": "Arme o fechamento somente com uma conta REAL conectada."}
        if (not state.get("terminal", {}).get("trade_allowed")
                or not account.get("trade_allowed") or not account.get("trade_expert")):
            return {"ok": False, "detail": "Negociação está desabilitada no terminal MT5."}
        self.real_close_armed = True
        self._real_close_account_fingerprint = f"{account.get('login')}@{account.get('server')}"
        return {"ok": True, "detail": "Fechamento individual REAL armado para esta sessão e conta."}

    def close_real_position(self, ticket: int, confirmation: str,
                            expected_account_fingerprint: str | None = None,
                            correlation_id: str | None = None) -> dict[str, Any]:
        with self._trade_lock, self._lock:
            if confirmation != "FECHAR POSIÇÃO REAL":
                return {"ok": False, "detail": "Confirmação incorreta; nenhuma ordem foi enviada."}
            state = self.state()
            account = state.get("account") or {}
            fingerprint = f"{account.get('login')}@{account.get('server')}"
            if (not state.get("connected") or account.get("mode") != "REAL"
                    or not self.real_close_armed or fingerprint != self._real_close_account_fingerprint
                    or (expected_account_fingerprint and fingerprint != expected_account_fingerprint)):
                return {"ok": False, "blocked": True,
                        "detail": "Fechamento REAL não armado para esta conta/servidor; nenhuma ordem enviada."}
            if (not state.get("terminal", {}).get("trade_allowed")
                    or not account.get("trade_allowed") or not account.get("trade_expert")):
                return {"ok": False, "detail": "Negociação desabilitada no terminal."}
            return self._close_position_market(ticket, fingerprint, "REAL", correlation_id)

    def _close_demo_position(self, ticket: int, confirmation: str,
                             expected_account_fingerprint: str | None = None,
                             correlation_id: str | None = None) -> dict[str, Any]:
        if confirmation != "FECHAR POSIÇÃO DEMO":
            return {"ok": False, "detail": "Confirmação incorreta; nenhuma ordem foi enviada."}
        state = self.state()
        mode = (state.get("account") or {}).get("mode")
        if mode != "DEMO":
            self.demo_armed = False
            self._demo_armed_account_fingerprint = None
            return {"ok": False, "blocked": mode in {"REAL", "CONTEST"},
                    "detail": "Fechamentos estão habilitados somente em conta DEMO conectada."}
        if not state.get("connected"):
            return {"ok": False, "detail": "O terminal MT5 não está conectado."}
        if not self.demo_armed:
            return {"ok": False, "detail": "Arme primeiro a execução DEMO com confirmação explícita."}
        account = state.get("account") or {}
        fingerprint = f"{account.get('login')}@{account.get('server')}"
        if fingerprint != self._demo_armed_account_fingerprint:
            self.demo_armed = False
            self._demo_armed_account_fingerprint = None
            return {"ok": False, "blocked": True, "detail": "O armamento não corresponde à conta DEMO atual; arme novamente."}
        if expected_account_fingerprint and fingerprint != expected_account_fingerprint:
            return {"ok": False, "blocked": True, "detail": "A conta DEMO mudou; fechamento cancelado."}
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "detail": self.last_error or "MT5 indisponível."}
        return self._close_position_market(ticket, fingerprint, "DEMO", correlation_id)

    def _close_position_market(self, ticket: int, fingerprint: str, mode: str,
                               correlation_id: str | None = None) -> dict[str, Any]:
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "detail": self.last_error or "MT5 indisponível."}
        found = mt5.positions_get(ticket=ticket)
        if not found:
            return {"ok": False, "detail": "A posição não foi encontrada; atualize a lista antes de tentar novamente."}
        position = found[0]
        tick = mt5.symbol_info_tick(position.symbol)
        symbol = mt5.symbol_info(position.symbol)
        if tick is None or symbol is None:
            return {"ok": False, "detail": "Cotação/especificação do símbolo indisponível. Nenhuma ordem foi enviada."}
        closing_buy = position.type == mt5.POSITION_TYPE_SELL
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": position.symbol, "volume": float(position.volume),
                   "type": mt5.ORDER_TYPE_BUY if closing_buy else mt5.ORDER_TYPE_SELL,
                   "position": int(position.ticket), "price": float(tick.ask if closing_buy else tick.bid),
                   "deviation": 20, "magic": int(position.magic),
                   "comment": f"ScalperLab {mode.lower()} close",
                   "type_time": mt5.ORDER_TIME_GTC, "type_filling": self._filling(mt5, symbol)}
        return self._send_and_reconcile(mt5, request, int(ticket), fingerprint, mode, correlation_id)

    def place_demo_smoke_order(self, confirmation: str,
                               correlation_id: str | None = None) -> dict[str, Any]:
        """Send one minimum-size EURUSD demo buy, reconcile it, then request its close."""
        with self._trade_lock, self._lock:
            return self._place_demo_smoke_order(confirmation, correlation_id)

    def _place_demo_smoke_order(self, confirmation: str,
                                correlation_id: str | None = None) -> dict[str, Any]:
        if confirmation != "ENVIAR TESTE DEMO":
            return {"ok": False, "detail": "Confirmação incorreta; nenhuma ordem foi enviada."}
        state = self.state()
        account = state.get("account") or {}
        if not state.get("connected") or account.get("mode") != "DEMO":
            return {"ok": False, "blocked": True,
                    "detail": "O teste de ordem exige terminal conectado em conta DEMO."}
        if not state.get("terminal", {}).get("trade_allowed"):
            return {"ok": False, "detail": "O terminal está com negociação desabilitada."}
        expected_account_fingerprint = f"{account.get('login')}@{account.get('server')}"
        mt5 = self._connect()
        if mt5 is None:
            return {"ok": False, "detail": self.last_error or "MT5 indisponível."}
        existing = mt5.positions_get()
        if existing is None:
            return {"ok": False, "detail": "Não foi possível consultar posições existentes; teste cancelado."}
        if existing:
            return {"ok": False, "detail": "Há posições abertas na conta. O teste foi cancelado para não interferir nelas."}
        existing_orders = mt5.orders_get()
        if existing_orders is None:
            return {"ok": False,
                    "detail": "Não foi possível consultar ordens pendentes; teste cancelado."}
        if existing_orders:
            return {"ok": False,
                    "detail": "Há ordens pendentes na conta. O teste foi cancelado para não interferir nelas."}

        symbols = mt5.symbols_get(group="*EURUSD*") or []
        tradable = [item for item in symbols
                    if item.name.upper().startswith("EURUSD")
                    and item.trade_mode == getattr(mt5, "SYMBOL_TRADE_MODE_FULL", 4)
                    and int(getattr(item, "order_mode", 0)) & getattr(mt5, "SYMBOL_ORDER_MARKET", 1)
                    and 0 < float(item.volume_min) <= 0.01]
        if not tradable:
            return {"ok": False, "detail": "Nenhum símbolo EURUSD disponível aceita ordem a mercado de no máximo 0,01 lote."}
        symbol = sorted(tradable, key=lambda item: (item.name.upper() != "EURUSD", item.name))[0]
        volume = float(symbol.volume_min)
        tick = mt5.symbol_info_tick(symbol.name)
        if tick is None or not float(tick.ask) > 0:
            return {"ok": False, "detail": "Cotação de compra EURUSD indisponível; nenhuma ordem foi enviada."}

        magic = 209221001
        comment = "SL1 demo test"
        request = {"action": mt5.TRADE_ACTION_DEAL, "symbol": symbol.name, "volume": volume,
                   "type": mt5.ORDER_TYPE_BUY, "price": float(tick.ask), "deviation": 20,
                   "magic": magic, "comment": self._correlated_comment(comment, correlation_id),
                   "type_time": mt5.ORDER_TIME_GTC,
                   "type_filling": self._filling(mt5, symbol)}
        try:
            check = mt5.order_check(request)
        except Exception as exc:
            return {"ok": False, "detail": f"Validação pré-envio falhou ({type(exc).__name__}); nenhuma ordem foi enviada."}
        if check is None or getattr(check, "retcode", None) not in {0, getattr(mt5, "TRADE_RETCODE_DONE", 10009)}:
            return {"ok": False, "detail": f"MT5 rejeitou a validação (retcode {getattr(check, 'retcode', 'indisponível')}); nenhuma ordem foi enviada."}
        final_state = self.state()
        final_account = final_state.get("account") or {}
        if (not final_state.get("connected") or final_account.get("mode") != "DEMO"
                or f"{final_account.get('login')}@{final_account.get('server')}" != expected_account_fingerprint
                or not final_state.get("terminal", {}).get("trade_allowed")):
            return {"ok": False, "blocked": True, "detail": "Conta, conexão ou permissão DEMO mudou; teste cancelado."}
        final_positions = mt5.positions_get()
        if final_positions is None or final_positions:
            return {"ok": False, "blocked": True, "detail": "Posições mudaram durante a validação; teste cancelado."}
        final_orders = mt5.orders_get()
        if final_orders is None or final_orders:
            return {"ok": False, "blocked": True,
                    "detail": "Ordens pendentes mudaram durante a validação; teste cancelado."}
        try:
            opened = mt5.order_send(request)
        except Exception as exc:
            return {"ok": False, "unknown": True, "position_may_remain": True,
                    "no_retry": True, "correlation_id": correlation_id,
                    "detail": f"Resultado da ordem de teste desconhecido ({type(exc).__name__}); consulte o terminal antes de qualquer nova tentativa."}
        if opened is None:
            return {"ok": False, "unknown": True, "position_may_remain": True,
                    "no_retry": True, "correlation_id": correlation_id,
                    "detail": f"O terminal não confirmou a ordem ({mt5.last_error()}); consulte posições/histórico, sem reenviar."}
        accepted = {getattr(mt5, "TRADE_RETCODE_DONE", 10009), getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)}
        if opened.retcode not in accepted:
            return {"ok": False, "detail": f"MT5 rejeitou a ordem de teste (retcode {opened.retcode})."}

        reconciled = mt5.positions_get(symbol=symbol.name)
        marker = f"SC{correlation_id.replace('-', '')[:10]}" if correlation_id else None
        matches = [position for position in (reconciled or []) if int(position.magic) == magic and (
            str(position.comment).startswith(comment) or (marker and marker in str(position.comment)))]
        if reconciled is None or len(matches) != 1:
            return {"ok": False, "unknown": True, "position_may_remain": True,
                    "correlation_id": correlation_id,
                    "detail": "Ordem aceita, mas a posição de teste não foi identificada com segurança. Não haverá repetição nem fechamento de posição desconhecida; confira o MT5.",
                    "symbol": symbol.name, "volume": volume, "open_order": int(getattr(opened, "order", 0)),
                    "open_deal": int(getattr(opened, "deal", 0))}

        test_position = matches[0]
        self.demo_armed = True
        self._demo_armed_account_fingerprint = expected_account_fingerprint
        close_result = self.close_demo_position(int(test_position.ticket), "FECHAR POSIÇÃO DEMO",
                                                expected_account_fingerprint=expected_account_fingerprint,
                                                correlation_id=correlation_id)
        self.demo_armed = False
        self._demo_armed_account_fingerprint = None
        self.real_close_armed = False
        self._real_close_account_fingerprint = None
        after = self.positions()
        our_position_remains = any(item.get("magic") == magic for item in after.get("items", [])) if after.get("available") else None
        ok = bool(close_result.get("ok") and after.get("available") and our_position_remains is False)
        return {"ok": ok, "correlation_id": correlation_id, "symbol": symbol.name,
                "side": "BUY", "requested_volume": volume,
                "filled_volume": float(test_position.volume),
                "filled_price": float(test_position.price_open),
                "open_retcode": int(opened.retcode), "volume": volume,
                "open_order": int(getattr(opened, "order", 0)), "open_deal": int(getattr(opened, "deal", 0)),
                "close": close_result, "position_remains": our_position_remains,
                "detail": "Ordem demo aberta, confirmada e fechada; posição reconciliada como encerrada." if ok
                else "A ordem demo foi aberta. O fechamento não foi confirmado; atualize posições no MT5 antes de nova ação.",
                "no_retry": True}

    def emergency_stop_demo(self, confirmation: str,
                            correlation_id: str | None = None) -> dict[str, Any]:
        with self._trade_lock, self._lock:
            return self._emergency_stop_demo(confirmation, correlation_id)

    def emergency_stop_real(self, confirmation: str,
                            correlation_id: str | None = None) -> dict[str, Any]:
        with self._trade_lock, self._lock:
            return self._emergency_stop_account(confirmation, "REAL", correlation_id)

    def _emergency_stop_demo(self, confirmation: str,
                             correlation_id: str | None = None) -> dict[str, Any]:
        return self._emergency_stop_account(confirmation, "DEMO", correlation_id)

    def _emergency_stop_account(self, confirmation: str, mode: str,
                                correlation_id: str | None = None) -> dict[str, Any]:
        def finish(result: dict[str, Any], status: str, *, remaining_count=None, reconciled=False):
            result = {**result, "status": status, "remaining_count": remaining_count,
                      "reconciled": bool(reconciled)}
            self.emergency_action = {"status": status, "detail": result.get("detail", ""),
                                     "updated_at": datetime.now(timezone.utc).isoformat(),
                                     "remaining_count": remaining_count,
                                     "reconciled": bool(reconciled)}
            return result

        expected_confirmation = f"FECHAR TODAS AS POSIÇÕES {mode}"
        if confirmation != expected_confirmation:
            return finish({"ok": False, "detail": "Confirmação incorreta. Nenhuma operação foi enviada."}, "failed")
        state = self.state()
        if (state.get("account") or {}).get("mode") != mode:
            self.demo_armed = False
            self._demo_armed_account_fingerprint = None
            self.real_close_armed = False
            self._real_close_account_fingerprint = None
            return finish({"ok": False, "blocked": True, "detail": f"Conta conectada não é {mode}; nenhuma posição foi fechada."}, "blocked")
        self.demo_armed = False
        self._demo_armed_account_fingerprint = None
        self.real_close_armed = False
        self._real_close_account_fingerprint = None
        if not state.get("connected"):
            return finish({"ok": False, "unknown": True,
                           "detail": f"Motor parado; terminal {mode} desconectado e posições não confirmadas.",
                           "results": []}, "unknown")
        account = state.get("account") or {}
        expected_account_fingerprint = f"{account.get('login')}@{account.get('server')}"
        positions = self.positions()
        if not positions["available"]:
            return finish({"ok": False, "detail": f"Motor parado; não foi possível confirmar as posições: {positions['detail']}", "results": []}, "unknown")
        if not positions["items"]:
            return finish({"ok": True, "detail": f"Parada confirmada: motor parado e nenhuma posição aberta em {mode}.",
                           "results": [], "remaining": []}, "completed", remaining_count=0, reconciled=True)
        if mode == "DEMO":
            self.demo_armed = True
            self._demo_armed_account_fingerprint = expected_account_fingerprint
            results = [self.close_demo_position(item["ticket"], "FECHAR POSIÇÃO DEMO",
                                                expected_account_fingerprint=expected_account_fingerprint,
                                                correlation_id=correlation_id)
                       for item in positions["items"]]
            self.demo_armed = False
            self._demo_armed_account_fingerprint = None
        else:
            self.real_close_armed = True
            self._real_close_account_fingerprint = expected_account_fingerprint
            results = [self.close_real_position(item["ticket"], "FECHAR POSIÇÃO REAL",
                                                 expected_account_fingerprint=expected_account_fingerprint,
                                                 correlation_id=correlation_id)
                       for item in positions["items"]]
            self.real_close_armed = False
            self._real_close_account_fingerprint = None
        remaining = self.positions()
        if not remaining.get("available"):
            return finish({"ok": False, "unknown": True,
                           "detail": "Motor parado; o MT5 não confirmou a lista final de posições. Confira o terminal antes de repetir.",
                           "results": results, "remaining": None}, "unknown")
        left = remaining["items"]
        ok = all(result.get("ok") for result in results) and not left
        detail = (f"Parada confirmada: todas as posições {mode} foram reconciliadas como fechadas."
                  if ok else f"Motor parado; fechamento incompleto. {len(left)} posição(ões) continuam abertas no MT5.")
        return finish({"ok": ok, "detail": detail, "results": results, "remaining": left},
                      "completed" if ok else "partial", remaining_count=len(left), reconciled=True)

    @staticmethod
    def _filling(mt5, symbol) -> int:
        flags = int(getattr(symbol, "filling_mode", 0))
        if flags & 2:
            return mt5.ORDER_FILLING_IOC
        if flags & 1:
            return mt5.ORDER_FILLING_FOK
        return mt5.ORDER_FILLING_RETURN

    def _send_and_reconcile(self, mt5, request: dict[str, Any], ticket: int,
                            expected_account_fingerprint: str, mode: str = "DEMO",
                            correlation_id: str | None = None) -> dict[str, Any]:
        request["comment"] = self._correlated_comment(request.get("comment", ""), correlation_id)
        try:
            check = mt5.order_check(request)
        except Exception as exc:
            return {"ok": False, "detail": f"Validação pré-envio falhou ({type(exc).__name__}); nenhuma repetição foi feita."}
        if check is None or getattr(check, "retcode", None) not in {0, getattr(mt5, "TRADE_RETCODE_DONE", 10009)}:
            return {"ok": False, "detail": f"MT5 rejeitou a validação (retcode {getattr(check, 'retcode', 'indisponível')}); nenhuma ordem foi enviada."}
        final_state = self.state()
        final_account = final_state.get("account") or {}
        if (not final_state.get("connected") or final_account.get("mode") != mode
                or f"{final_account.get('login')}@{final_account.get('server')}" != expected_account_fingerprint
                or not final_state.get("terminal", {}).get("trade_allowed")
                or not final_account.get("trade_allowed") or not final_account.get("trade_expert")):
            return {"ok": False, "blocked": True, "detail": f"Conta ou conexão {mode} mudou antes do fechamento; envio cancelado."}
        current = mt5.positions_get(ticket=ticket)
        if current is None or len(current) != 1:
            return {"ok": False, "blocked": True, "detail": "A posição mudou durante a validação; fechamento cancelado."}
        try:
            result = mt5.order_send(request)
        except Exception as exc:
            return {"ok": False, "unknown": True, "no_retry": True,
                    "correlation_id": correlation_id,
                    "detail": f"Resultado do envio desconhecido ({type(exc).__name__}); atualize posições e histórico antes de qualquer nova ação."}
        if result is None:
            return {"ok": False, "unknown": True, "no_retry": True,
                    "correlation_id": correlation_id,
                    "detail": f"MT5 não confirmou o envio ({mt5.last_error()}); não reenvie antes da reconciliação."}
        accepted = {getattr(mt5, "TRADE_RETCODE_DONE", 10009), getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010)}
        if result.retcode not in accepted:
            return {"ok": False, "retcode": int(result.retcode),
                    "correlation_id": correlation_id,
                    "detail": f"MT5 rejeitou a ordem (retcode {result.retcode}); posição {ticket} não foi confirmada como fechada."}
        remaining = mt5.positions_get(ticket=ticket)
        prior_volume = float(current[0].volume)
        remaining_volume = sum(float(position.volume) for position in (remaining or []))
        return {"ok": remaining is not None and len(remaining) == 0,
                "partial": bool(remaining), "unknown": remaining is None,
                "correlation_id": correlation_id, "requested_volume": prior_volume,
                "filled_volume": max(0.0, prior_volume - remaining_volume),
                "filled_price": float(getattr(result, "price", 0.0)),
                "remaining_volume": remaining_volume,
                "detail": "Posição reconciliada como fechada." if remaining is not None and len(remaining) == 0
                else "Envio aceito, mas posição remanescente/estado desconhecido; atualize antes de nova ação.",
                "retcode": int(result.retcode), "order": int(getattr(result, "order", 0)),
                "deal": int(getattr(result, "deal", 0))}
