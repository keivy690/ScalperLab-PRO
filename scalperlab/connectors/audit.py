from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..db import Database


_ORDER_ACTIONS = {
    "submit_order",
    "send_demo_strategy_order",
    "send_real_strategy_order",
    "send_demo_analyst_order",
    "send_real_analyst_order",
    "place_demo_smoke_order",
    "close_demo_position",
    "close_real_position",
    "emergency_stop_demo",
    "emergency_stop_real",
}
_UNRESOLVED_STATUSES = {
    "prepared",
    "unknown",
    "partial",
    "acknowledged",
    "pending_reconciliation",
}


class AuditedTradingPort:
    """Persist every order action before RPC and reconcile it against terminal history."""

    def __init__(
        self, connector: Any, database: Database, *, symbol_mappings: dict[str, str] | None = None
    ) -> None:
        self.connector = connector
        self.database = database
        self.terminal_id = connector.terminal_id
        self.symbol_mappings = {
            key.upper(): value for key, value in (symbol_mappings or {}).items()
        }
        self._reverse_symbols = {value: key for key, value in self.symbol_mappings.items()}

    def __getattr__(self, name: str):
        target = getattr(self.connector, name)
        if name not in _ORDER_ACTIONS:
            return target

        def audited_call(*args, **kwargs):
            return self._invoke(name, target, args, kwargs)

        return audited_call

    def _request_data(
        self, method: str, args: tuple, kwargs: dict[str, Any], correlation_id: str
    ) -> dict[str, Any]:
        fields = {
            "send_demo_strategy_order": (
                "symbol",
                "side",
                "volume",
                "stop",
                "target",
                "strategy_id",
                "expected_account_fingerprint",
                "risk_cash",
            ),
            "send_real_strategy_order": (
                "symbol",
                "side",
                "volume",
                "stop",
                "target",
                "strategy_id",
                "expected_account_fingerprint",
                "risk_cash",
            ),
            "send_demo_analyst_order": (
                "symbol",
                "side",
                "volume",
                "stop",
                "target",
                "expected_account_fingerprint",
                "risk_cash",
                "max_spread",
                "min_reward_risk",
            ),
            "send_real_analyst_order": (
                "symbol",
                "side",
                "volume",
                "stop",
                "target",
                "expected_account_fingerprint",
                "risk_cash",
                "max_spread",
                "min_reward_risk",
            ),
            "close_demo_position": ("ticket", "confirmation", "expected_account_fingerprint"),
            "close_real_position": ("ticket", "confirmation", "expected_account_fingerprint"),
            "place_demo_smoke_order": (),
            "emergency_stop_demo": (),
            "emergency_stop_real": (),
            "submit_order": (),
        }
        if method == "submit_order":
            raw = args[0] if args and isinstance(args[0], dict) else {}
            selected = {
                key: raw[key]
                for key in (
                    "engine",
                    "mode",
                    "symbol",
                    "side",
                    "volume",
                    "stop",
                    "target",
                    "strategy_id",
                    "risk_cash",
                )
                if key in raw
            }
        elif method == "place_demo_smoke_order":
            selected = {"symbol": "EURUSD", "requested_volume_max": 0.01}
        else:
            names = fields[method]
            sensitive = {"confirmation", "expected_account_fingerprint"}
            selected = {key: value for key, value in zip(names, args) if key not in sensitive}
            selected.update(
                {key: kwargs[key] for key in names if key in kwargs and key not in sensitive}
            )
        canonical = selected.get("symbol")
        if canonical:
            canonical_text = str(canonical)
            broker_symbol = self.symbol_mappings.get(canonical_text.upper(), canonical_text)
            selected["symbol"] = canonical_text
            selected["canonical_symbol"] = self._reverse_symbols.get(
                broker_symbol, canonical_text.upper()
            )
            selected["broker_symbol"] = broker_symbol
        account_fingerprint = kwargs.get("expected_account_fingerprint")
        if account_fingerprint is None:
            fingerprint_index = (
                6
                if "strategy_order" in method
                else 5
                if "analyst_order" in method
                else 2
                if method in {"close_demo_position", "close_real_position"}
                else None
            )
            if fingerprint_index is not None and len(args) > fingerprint_index:
                account_fingerprint = args[fingerprint_index]
        if method == "submit_order" and args and isinstance(args[0], dict):
            account_fingerprint = args[0].get("account_fingerprint")
        if account_fingerprint:
            selected["account_fingerprint_sha256"] = hashlib.sha256(
                str(account_fingerprint).encode("utf-8")
            ).hexdigest()[:16]
        selected["mode"] = (
            str(selected.get("mode", "DEMO")).upper()
            if method == "submit_order"
            else "REAL"
            if "real" in method
            else "DEMO"
            if "demo" in method
            else None
        )
        selected["correlation_id"] = correlation_id
        selected["broker_marker"] = self._marker(correlation_id)
        return selected

    @staticmethod
    def _marker(correlation_id: str) -> str:
        return f"SC{correlation_id.replace('-', '')[:10]}".upper()

    def _invoke(self, method: str, target, args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
        correlation_id = str(uuid.uuid4())
        started = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        request = self._request_data(method, args, kwargs, correlation_id)
        try:
            state = self.connector.state()
            account = state.get("account") or {}
            fingerprint = (
                f"{account['login']}@{account['server']}"
                if account.get("login") and account.get("server")
                else None
            )
            if fingerprint:
                request["account_fingerprint_sha256"] = hashlib.sha256(
                    fingerprint.encode("utf-8")
                ).hexdigest()[:16]
                request["observed_account_mode"] = account.get("mode")
        except Exception:
            pass
        if method in {"close_demo_position", "close_real_position"}:
            ticket = request.get("ticket")
            snapshot = self._safe_positions()
            position = next(
                (item for item in snapshot.get("items", []) if item.get("ticket") == ticket), None
            )
            if snapshot.get("available") and position:
                self._add_position_request_metadata(request, position)
        elif method in {"emergency_stop_demo", "emergency_stop_real"}:
            snapshot = self._safe_positions()
            if snapshot.get("available"):
                request["positions_before"] = [
                    {key: item.get(key) for key in ("ticket", "symbol", "type", "volume", "magic")}
                    for item in snapshot.get("items", [])
                ]
        self.database.create_trade_audit(
            correlation_id=correlation_id,
            terminal_id=self.terminal_id,
            method=method,
            started_at=started,
            request=request,
        )

        call_args = args
        call_kwargs = dict(kwargs)
        if method == "submit_order":
            order = dict(args[0]) if args and isinstance(args[0], dict) else {}
            order["correlation_id"] = correlation_id
            call_args = (order, *args[1:])
        else:
            call_kwargs["correlation_id"] = correlation_id

        try:
            result = target(*call_args, **call_kwargs)
            if not isinstance(result, dict):
                result = {"ok": bool(result), "value": result}
        except Exception as exc:
            result = {
                "ok": False,
                "unknown": True,
                "no_retry": True,
                "position_may_remain": True,
                "detail": f"Ação interrompida ({type(exc).__name__}); reconciliação necessária.",
            }
        result = {**result, "correlation_id": correlation_id}
        status = self._status(result)
        try:
            self.database.update_trade_audit(correlation_id, status=status, result=result)
        except Exception as exc:
            result["audit_persisted"] = False
            result["audit_warning"] = (
                f"Resultado operacional recebido, mas a atualização da trilha falhou "
                f"({type(exc).__name__}); reconciliação necessária antes de nova ação."
            )
            return result
        if status in _UNRESOLVED_STATUSES:
            self.reconcile(correlation_id)
        return result

    def _safe_positions(self) -> dict[str, Any]:
        try:
            snapshot = self.connector.positions()
            if isinstance(snapshot, dict):
                return snapshot
        except Exception:
            pass
        return {"available": False, "items": []}

    def _add_position_request_metadata(
        self, request: dict[str, Any], position: dict[str, Any]
    ) -> None:
        broker_symbol = str(position.get("symbol", ""))
        canonical_symbol = self._reverse_symbols.get(broker_symbol, broker_symbol.upper())
        request.update(
            {
                "canonical_symbol": canonical_symbol,
                "broker_symbol": broker_symbol,
                "requested_volume": position.get("volume"),
                "side": position.get("type"),
                "position_magic": position.get("magic"),
            }
        )

    @staticmethod
    def _status(result: dict[str, Any]) -> str:
        if result.get("unknown"):
            return "pending_reconciliation"
        nested_results = result.get("results", [])
        if (
            result.get("partial")
            or result.get("status") == "partial"
            or result.get("position_remains") is True
            or result.get("remaining_count", 0)
            or any(item.get("partial") for item in nested_results if isinstance(item, dict))
        ):
            return "partial"
        if result.get("ok"):
            return "acknowledged"
        if result.get("blocked"):
            return "blocked"
        return "rejected"

    @staticmethod
    def _result_ids(result: Any) -> dict[str, set[int]]:
        collected = {"order": set(), "deal": set(), "ticket": set()}
        if isinstance(result, dict):
            for key, value in result.items():
                kind = (
                    key
                    if key in collected
                    else (
                        "order"
                        if key.endswith("_order")
                        else "deal"
                        if key.endswith("_deal")
                        else None
                    )
                )
                if kind:
                    try:
                        number = int(value)
                        if number > 0:
                            collected[kind].add(number)
                    except (TypeError, ValueError):
                        pass
                else:
                    if key in {"positions", "remaining"}:
                        continue
                    nested = AuditedTradingPort._result_ids(value)
                    for name in collected:
                        collected[name].update(nested[name])
        elif isinstance(result, list):
            for value in result:
                nested = AuditedTradingPort._result_ids(value)
                for name in collected:
                    collected[name].update(nested[name])
        return collected

    def reconcile(self, correlation_id: str) -> dict[str, Any]:
        record = self.database.get_trade_audit(correlation_id)
        if record is None or record["terminal_id"] != self.terminal_id:
            return {"correlation_id": correlation_id, "status": "not_found"}
        started = datetime.fromisoformat(record["started_at"].replace("Z", "+00:00"))
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        date_from = (started.astimezone(timezone.utc) - timedelta(minutes=2)).isoformat()
        date_to = datetime.now(timezone.utc).isoformat()
        orders = self._safe_history("history_orders", date_from, date_to)
        deals = self._safe_history("history_deals", date_from, date_to)
        positions = self._safe_positions()

        request = record["request"]
        result = record["result"]
        marker = self._marker(correlation_id)
        ids = self._result_ids(result)
        try:
            if request.get("ticket") is not None:
                ids["ticket"].add(int(request["ticket"]))
            for item in request.get("positions_before", []):
                if item.get("ticket") is not None:
                    ids["ticket"].add(int(item["ticket"]))
        except (TypeError, ValueError):
            pass
        all_orders = orders.get("items", [])
        matched_orders = [
            item
            for item in all_orders
            if (
                marker in str(item.get("comment", "")).upper()
                or int(item.get("ticket", 0) or 0) in ids["order"]
            )
        ]
        order_tickets = {int(item.get("ticket", 0) or 0) for item in matched_orders}
        all_deals = deals.get("items", [])
        matched_deals = [
            item
            for item in all_deals
            if (
                marker in str(item.get("comment", "")).upper()
                or int(item.get("order", 0) or 0) in order_tickets
                or int(item.get("ticket", 0) or 0) in ids["deal"]
            )
        ]
        correlated_positions = [
            item
            for item in positions.get("items", [])
            if (
                marker in str(item.get("comment", "")).upper()
                or int(item.get("ticket", 0) or 0) in ids["ticket"]
            )
        ]

        available = bool(
            orders.get("available") and deals.get("available") and positions.get("available")
        )
        found = bool(matched_orders or matched_deals or correlated_positions)
        observed_broker_symbol = next(
            (str(item.get("symbol")) for item in matched_deals if item.get("symbol")), None
        )
        if observed_broker_symbol is None:
            observed_broker_symbol = next(
                (str(item.get("symbol")) for item in matched_orders if item.get("symbol")), None
            )
        entry_deals = [
            item
            for item in matched_deals
            if item.get("entry") is None or item.get("entry") in {0, 2}
        ]
        exit_deals = [
            item
            for item in matched_deals
            if item.get("entry") is None or item.get("entry") in {1, 2, 3}
        ]
        close_action = "close" in record["method"] or "emergency_stop" in record["method"]
        action_deals = exit_deals if close_action else entry_deals
        evidence = {
            "checked_at": date_to,
            "history_orders_available": bool(orders.get("available")),
            "history_deals_available": bool(deals.get("available")),
            "positions_available": bool(positions.get("available")),
            "match_found": found,
            "orders": matched_orders,
            "deals": matched_deals,
            "positions": correlated_positions,
            "requested_symbol": request.get("canonical_symbol") or request.get("symbol"),
            "broker_symbol": request.get("broker_symbol") or observed_broker_symbol,
            "filled_volume": sum(float(item.get("volume", 0) or 0) for item in action_deals),
            "weighted_fill_price": self._weighted_price(action_deals),
            "closed_volume": sum(float(item.get("volume", 0) or 0) for item in exit_deals),
            "weighted_close_price": self._weighted_price(exit_deals),
            "costs": {
                "commission": sum(float(item.get("commission", 0) or 0) for item in matched_deals),
                "swap": sum(float(item.get("swap", 0) or 0) for item in matched_deals),
                "fee": sum(float(item.get("fee", 0) or 0) for item in matched_deals),
                "profit": sum(float(item.get("profit", 0) or 0) for item in matched_deals),
            },
            "detail": "Histórico e posição correlacionados."
            if available and found
            else "Aguardando correspondência no histórico; nenhuma ordem foi reenviada."
            if available
            else "Histórico/posições indisponíveis; reconciliação permanece pendente.",
        }
        still_open_close = close_action and bool(correlated_positions)
        status = (
            "partial"
            if available and found and still_open_close
            else "reconciled"
            if available and found
            else record["status"]
        )
        if status == "prepared":
            status = "pending_reconciliation"
        self.database.update_trade_audit(correlation_id, status=status, evidence=evidence)
        return {"correlation_id": correlation_id, "status": status, "evidence": evidence}

    @staticmethod
    def _weighted_price(deals: list[dict[str, Any]]) -> float | None:
        weighted = [
            (float(item.get("volume", 0) or 0), float(item.get("price", 0) or 0))
            for item in deals
            if float(item.get("volume", 0) or 0) > 0
        ]
        total = sum(volume for volume, _price in weighted)
        return sum(volume * price for volume, price in weighted) / total if total else None

    def _safe_history(self, method: str, date_from: str, date_to: str) -> dict[str, Any]:
        try:
            history = getattr(self.connector, method)(date_from, date_to)
            if isinstance(history, dict):
                return history
        except Exception:
            pass
        return {"available": False, "items": []}

    def reconcile_pending(
        self, *, correlation_id: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        if correlation_id:
            result = self.reconcile(correlation_id)
            return [] if result.get("status") == "not_found" else [result]
        records = self.database.list_trade_audit(
            limit=max(1, min(limit, 10)), statuses=_UNRESOLVED_STATUSES
        )
        return [self.reconcile(item["correlation_id"]) for item in records]

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self.database.list_trade_audit(limit=limit)
