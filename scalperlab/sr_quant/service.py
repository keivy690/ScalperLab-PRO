from __future__ import annotations

import copy
import hashlib
import threading
from datetime import datetime, timezone
from typing import Any

from .core import RULE_VERSION, evaluate_bundle, read_live_bundle


class SrResearchService:
    """Read-only observation of at most two broker symbols on closed M5 bars."""

    def __init__(self, database: Any, port: Any, interval_seconds: int = 60) -> None:
        self.database = database
        self.port = port
        self.interval_seconds = max(30, int(interval_seconds))
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._state: dict[str, Any] = {
            "running": False, "mode": "research_only", "symbols": [],
            "phase": "parado", "detail": "Pesquisa S/R não iniciada.",
            "last_cycle_at": None, "last_results": [], "rule_version": RULE_VERSION,
        }
        self._account_sha256: str | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**copy.deepcopy(self._state),
                    "busy": bool(self._thread and self._thread.is_alive())}

    def start(self, symbols: list[str]) -> dict[str, Any]:
        if not isinstance(symbols, list) or not 1 <= len(symbols) <= 2:
            return {"ok": False, "detail": "Selecione um ou dois ativos do Market Watch."}
        if any(not isinstance(item, str) or not item.strip() for item in symbols):
            return {"ok": False, "detail": "Símbolo inválido."}
        selected = list(dict.fromkeys(item.strip() for item in symbols))
        if len(selected) != len(symbols):
            return {"ok": False, "detail": "Selecione ativos diferentes."}
        state = self.port.state()
        account = state.get("account") or {}
        if not state.get("connected") or not account.get("login") or not account.get("server"):
            return {"ok": False, "detail": "Conecte o MT5 e confirme a conta antes da pesquisa."}
        validation = self.port.validate_market_symbols(selected)
        if not validation.get("available") or not validation.get("valid"):
            return {"ok": False, "detail": validation.get("detail") or "Ativo fora do Market Watch."}
        terminal_id = str(getattr(self.port, "terminal_id", "default"))
        fingerprint = f'{terminal_id}:{account["login"]}@{account["server"]}'
        identity = hashlib.sha256(fingerprint.encode()).hexdigest()
        with self._lock:
            if self._state["running"]:
                return {"ok": False, "detail": "Pesquisa S/R já está em execução."}
            if self._thread is not None and self._thread.is_alive():
                return {"ok": False, "detail": "Aguarde a leitura MT5 anterior terminar antes de reiniciar a pesquisa."}
            self._account_sha256 = identity
            self._frame_cache.clear()
            self._stop.clear()
            self._state.update(running=True, symbols=selected, phase="inicializando",
                               detail="Pesquisa sem envio de ordens iniciada.", last_results=[])
            self._thread = threading.Thread(target=self._loop, name="scalperlab-sr-research",
                                            daemon=True)
            self._thread.start()
        return {"ok": True, "detail": "Pesquisa S/R iniciada sem envio de ordens."}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._state.update(running=False, phase="finalizando",
                               detail="Finalizando leitura S/R do MT5; nenhum motor de ordens foi armado.")
            self._stop.set()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        if thread and thread.is_alive():
            return {"ok": True, "detail": "Parada solicitada; aguarde a leitura MT5 atual terminar."}
        with self._lock:
            self._state.update(phase="parado", detail="Pesquisa S/R parada; sem envio de ordens.")
        return {"ok": True, "detail": "Pesquisa S/R parada."}

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if not self._state["running"]:
                    return
                symbols = list(self._state["symbols"])
                expected_identity = self._account_sha256
            terminal = self.port.state()
            account = terminal.get("account") or {}
            terminal_id = str(getattr(self.port, "terminal_id", "default"))
            fingerprint = (f'{terminal_id}:{account.get("login")}@{account.get("server")}'
                           if account.get("login") and account.get("server") else "")
            if not terminal.get("connected") or hashlib.sha256(fingerprint.encode()).hexdigest() != expected_identity:
                with self._lock:
                    self._state.update(running=False, phase="conta_alterada",
                                       detail="Conta/terminal mudou; pesquisa S/R interrompida.")
                self._stop.set()
                return
            results = []
            for symbol in symbols:
                if self._stop.is_set():
                    break
                try:
                    bundle = read_live_bundle(self.port, symbol,
                                              frame_cache=self._frame_cache)
                    if not bundle.get("ok"):
                        result = {"symbol": symbol, "version": RULE_VERSION,
                                  "mode": "research_only", "order_eligible": False,
                                  "status": "DADOS_INSUFICIENTES", "detail": bundle.get("detail"),
                                  "frame_last_closed": {"M5": None},
                                  "filter_counts": {"connector_unavailable": 1}}
                    else:
                        result = evaluate_bundle(bundle)
                        result["connector_diagnostics"] = bundle["connector_diagnostics"]
                        if result["frame_last_closed"].get("M5"):
                            self.database.save_sr_evaluation(
                                account_sha256=expected_identity, result=result)
                    results.append(result)
                except Exception as exc:
                    results.append({"symbol": symbol, "version": RULE_VERSION,
                                    "mode": "research_only", "order_eligible": False,
                                    "status": "FALHA_SEGURA", "detail": type(exc).__name__,
                                    "filter_counts": {"research_exception": 1}})
            with self._lock:
                if self._state["running"]:
                    self._state.update(phase="observando", last_results=results,
                                       last_cycle_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       detail=f"Último ciclo S/R: {len(results)} ativo(s); sem envio de ordens.")
            self._stop.wait(self.interval_seconds)
        with self._lock:
            if self._state["phase"] == "finalizando":
                self._state.update(phase="parado", detail="Pesquisa S/R parada; sem envio de ordens.")
