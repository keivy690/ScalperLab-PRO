from __future__ import annotations

import copy
import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Any

from ..mt5_time import MAX_FUTURE_TIME_SKEW_SECONDS, MAX_TICK_AGE_SECONDS
from .core import (RULE_VERSION, evaluate_live_broker_bundle,
                   read_live_broker_bundle)

SR_DEMO_CONFIRMATION = "INICIAR S/R SOMENTE DEMO"


class SrResearchService:
    """S/R observation or explicitly armed DEMO execution on closed M5 bars."""

    def __init__(self, database: Any, port: Any, interval_seconds: int = 60,
                 clock_service: Any | None = None, risk_settings: Any | None = None) -> None:
        self.database = database
        self.port = port
        self.clock_service = clock_service
        self.risk_settings = risk_settings
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
        self._account_fingerprint: str | None = None
        self.port.disarm_order_engine("sr_quant")

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {**copy.deepcopy(self._state),
                    "busy": bool(self._thread and self._thread.is_alive())}

    def start(self, symbols: list[str], mode: str = "research_only",
              confirmation: str = "") -> dict[str, Any]:
        if mode not in {"research_only", "demo"}:
            return {"ok": False, "detail": "Modo S/R inválido; use observação ou DEMO."}
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
        fingerprint_account = f'{account["login"]}@{account["server"]}'
        if mode == "demo":
            if confirmation != SR_DEMO_CONFIRMATION:
                return {"ok": False, "detail": f"Digite exatamente: {SR_DEMO_CONFIRMATION}."}
            if (account.get("mode") != "DEMO"
                    or not state.get("terminal", {}).get("trade_allowed")
                    or not account.get("trade_allowed") or not account.get("trade_expert")):
                return {"ok": False, "detail": "Execução S/R requer conta DEMO e negociação habilitada."}
            catalog = self.port.market_watch_catalog()
            items = {item.get("broker_symbol"): item for item in catalog.get("items", [])}
            if not catalog.get("available") or any(
                    not items.get(symbol, {}).get("trade_enabled") for symbol in selected):
                return {"ok": False, "detail": "Selecione somente ativos negociáveis do Market Watch."}
            if self.clock_service is None or not self.clock_service.is_verified(
                    terminal_id=getattr(self.port, "terminal_id", None),
                    account_fingerprint=fingerprint_account):
                return {"ok": False, "detail": "Valide o horário UTC para esta conta antes de iniciar DEMO."}
            if self.risk_settings is None:
                return {"ok": False, "detail": "Perfil de lote e risco indisponível."}
            daily = self.risk_settings.daily_check(self.port, account)
            if not daily.get("ok"):
                return daily
        terminal_id = str(getattr(self.port, "terminal_id", "default"))
        fingerprint = f'{terminal_id}:{account["login"]}@{account["server"]}'
        identity = hashlib.sha256(fingerprint.encode()).hexdigest()
        with self._lock:
            if self._state["running"]:
                return {"ok": False, "detail": "Pesquisa S/R já está em execução."}
            if self._thread is not None and self._thread.is_alive():
                return {"ok": False, "detail": "Aguarde a leitura MT5 anterior terminar antes de reiniciar a pesquisa."}
            self._account_sha256 = identity
            self._account_fingerprint = fingerprint_account
            self._frame_cache.clear()
            self._stop.clear()
            if mode == "demo" and not self.port.arm_order_engine(
                    "sr_quant", "DEMO", fingerprint_account):
                return {"ok": False, "detail": "Outro motor de ordens está armado."}
            self._state.update(running=True, mode=mode, symbols=selected,
                               phase="inicializando", last_results=[],
                               detail=("S/R DEMO armado; ordens dependem de sinal e preflight."
                                       if mode == "demo" else "Pesquisa S/R sem ordens iniciada."))
            self._thread = threading.Thread(target=self._loop, name="scalperlab-sr-research",
                                            daemon=True)
            self._thread.start()
        return {"ok": True, "detail": ("S/R DEMO iniciado; aguardando sinal confirmado."
                                        if mode == "demo" else "Pesquisa S/R iniciada sem envio de ordens.")}

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self._state.update(running=False, phase="finalizando",
                               detail="Finalizando leitura S/R do MT5; posições abertas permanecem no MT5.")
            self._stop.set()
            self.port.disarm_order_engine("sr_quant")
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=3)
        if thread and thread.is_alive():
            return {"ok": True, "detail": "Parada solicitada; aguarde a leitura MT5 atual terminar."}
        with self._lock:
            self._state.update(phase="parado", mode="research_only",
                               detail="S/R parado; posições abertas permanecem no MT5.")
        return {"ok": True, "detail": "Pesquisa S/R parada."}

    def _loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                if not self._state["running"]:
                    return
                symbols = list(self._state["symbols"])
                expected_identity = self._account_sha256
                run_mode = self._state["mode"]
            try:
                terminal = self.port.state()
            except Exception as exc:
                with self._lock:
                    self._state.update(running=False, phase="conector_indisponivel",
                                       detail=f"Conector MT5 falhou ({type(exc).__name__}); S/R parado.")
                    self._stop.set()
                    self.port.disarm_order_engine("sr_quant")
                return
            account = terminal.get("account") or {}
            terminal_id = str(getattr(self.port, "terminal_id", "default"))
            fingerprint = (f'{terminal_id}:{account.get("login")}@{account.get("server")}'
                           if account.get("login") and account.get("server") else "")
            if not terminal.get("connected") or hashlib.sha256(fingerprint.encode()).hexdigest() != expected_identity:
                with self._lock:
                    self._state.update(running=False, phase="conta_alterada",
                                       detail="Conta/terminal mudou; pesquisa S/R interrompida.")
                    self.port.disarm_order_engine("sr_quant")
                self._stop.set()
                return
            results = []
            for symbol in symbols:
                if self._stop.is_set():
                    break
                try:
                    bundle = read_live_broker_bundle(self.port, symbol)
                    try:
                        if (bundle.get("ok") and bundle.get("terminal_id") == terminal_id
                                and str(bundle["account"].get("login")) == str(account["login"])
                                and str(bundle["account"].get("server")) == str(account["server"])):
                            self.database.archive_sr_time_sample(
                                account_sha256=expected_identity,
                                sample=bundle["raw_sample"])
                    except Exception as exc:
                        self.database.save_sr_data_event(
                            account_sha256=expected_identity, symbol=symbol,
                            code="forward_archive_failed", detail=type(exc).__name__)
                    if not bundle.get("ok"):
                        code = str(bundle.get("code") or "connector_unavailable")
                        result = {"symbol": symbol, "version": RULE_VERSION,
                                  "mode": run_mode, "order_eligible": False,
                                  "code": code,
                                  "status": "DADOS_INSUFICIENTES", "detail": bundle.get("detail"),
                                  "frame_last_closed": {"M5": None},
                                  "filter_counts": {code: 1}}
                        self.database.save_sr_data_event(
                            account_sha256=expected_identity, symbol=symbol,
                            code=code, detail=str(bundle.get("detail") or "Dados MT5 indisponíveis."))
                    else:
                        result = evaluate_live_broker_bundle(bundle)
                        result["mode"] = run_mode
                        result["connector_diagnostics"] = bundle["connector_diagnostics"]
                        if run_mode == "demo":
                            self._maybe_execute(symbol, result, bundle)
                        if result["frame_last_closed"].get("M5"):
                            self.database.save_sr_evaluation(
                                account_sha256=expected_identity, result=result)
                    results.append(result)
                except Exception as exc:
                    results.append({"symbol": symbol, "version": RULE_VERSION,
                                    "mode": run_mode, "order_eligible": False,
                                    "status": "FALHA_SEGURA", "detail": type(exc).__name__,
                                    "filter_counts": {"research_exception": 1}})
                    if run_mode == "demo":
                        self.stop()
                        self.database.add_log("CRITICAL", f"S/R DEMO interrompido: {type(exc).__name__}")
            with self._lock:
                self._state.update(last_results=results,
                                   last_cycle_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
                if self._state["running"]:
                    self._state.update(phase="observando",
                                       detail=(f"Último ciclo S/R: {len(results)} ativo(s); "
                                               + ("DEMO armado, aguardando sinal/preflight."
                                                  if run_mode == "demo" else "somente observação.")))
            self._stop.wait(self.interval_seconds)
        with self._lock:
            if self._state["phase"] == "finalizando":
                self._state.update(phase="parado", mode="research_only",
                                   detail="S/R parado; posições abertas permanecem no MT5.")

    def _maybe_execute(self, symbol: str, result: dict[str, Any],
                       bundle: dict[str, Any]) -> None:
        """One DEMO intent for one closed candle; gateway owns final order preflight."""
        candidates = [item for item in result.get("candidates", [])
                      if item.get("status") == "CANDIDATE_RESEARCH_ONLY"]
        if not candidates or len({item["side"] for item in candidates}) != 1:
            result["execution_status"] = "SEM_SINAL_ELEGIVEL"
            return
        candidate = candidates[0]
        tick = bundle["tick"]
        signal_age = int(tick["time"]) - int(candidate["signal_bar_open_utc"]) - 300
        if signal_age < 0 or signal_age > 120:
            result["execution_status"] = "SINAL_EXPIRADO"
            return
        age = time.time() - float(tick.get("time") or 0)
        if age < -MAX_FUTURE_TIME_SKEW_SECONDS or age > MAX_TICK_AGE_SECONDS:
            result["execution_status"] = "COTACAO_DESATUALIZADA"
            return
        terminal = self.port.state()
        account = terminal.get("account") or {}
        fingerprint = f"{account.get('login')}@{account.get('server')}"
        with self._lock:
            expected = self._account_fingerprint
            active = self._state["running"] and self._state["mode"] == "demo"
        if (not active or fingerprint != expected or account.get("mode") != "DEMO"
                or not terminal.get("connected")
                or not terminal.get("terminal", {}).get("trade_allowed")
                or not account.get("trade_allowed") or not account.get("trade_expert")):
            result["execution_status"] = "CONTA_OU_MOTOR_ALTERADO"
            return
        daily = self.risk_settings.daily_check(self.port, account)
        if not daily.get("ok"):
            result["execution_status"] = "LIMITE_DIARIO_INDISPONIVEL"
            result["execution_detail"] = daily.get("detail")
            self.stop()
            return
        side = candidate["side"]
        entry = float(tick["ask"] if side == "BUY" else tick["bid"])
        stop = float(candidate["stop"])
        target = (entry + 1.5 * (entry - stop) if side == "BUY"
                  else entry - 1.5 * (stop - entry))
        if ((side == "BUY" and not stop < entry < target)
                or (side == "SELL" and not target < entry < stop)):
            result["execution_status"] = "PRECO_INVALIDOU_SINAL"
            return
        policy = self.risk_settings.profile("strategy")
        risk_cash = min(self.risk_settings.budget("strategy", account),
                        float(daily["remaining_cash"]))
        if risk_cash <= 0:
            result["execution_status"] = "RISCO_INDISPONIVEL"
            return
        sizing = self.port.risk_volume(
            symbol, side, entry, stop, risk_cash, policy["max_volume"], policy=policy)
        candidate["sizing"] = sizing
        if not sizing.get("ok"):
            result["execution_status"] = "RISCO_BLOQUEADO"
            result["execution_detail"] = sizing.get("detail")
            return
        with self._lock:
            if not self._state["running"] or self._state["mode"] != "demo":
                result["execution_status"] = "MOTOR_PARADO"
                return
            clock_ok = (self.clock_service is not None
                        and self.clock_service.is_currently_verified(
                            terminal_id=getattr(self.port, "terminal_id", None),
                            account_fingerprint=expected))
            if not clock_ok:
                result["execution_status"] = "RELOGIO_UTC_INVALIDO"
                self.stop()
                return
            signal_utc = int(candidate["signal_bar_open_utc"])
            reserved = self.database.reserve_sr_order_signal(
                account_sha256=self._account_sha256, symbol=symbol,
                rule_version=RULE_VERSION, strategy=candidate["strategy"],
                signal_bar_utc=signal_utc)
            if not reserved:
                result["execution_status"] = "SINAL_JA_PROCESSADO"
                return
            result["order_eligible"] = True
            response = self.port.send_demo_sr_order(
                symbol, side, sizing["volume"], stop, target, expected,
                risk_cash, float(result["atr14_m5"]) * 0.08, 1.5,
                risk_policy=policy)
        reconciled = response.get("ok") is True and response.get("reconciled") is True
        result["execution_status"] = (
            "CONFIRMADA_MT5" if reconciled else
            "ACEITA_AGUARDANDO_RECONCILIACAO" if response.get("ok") else
            "RESULTADO_DESCONHECIDO" if response.get("unknown")
            or response.get("position_may_remain") else "NAO_EXECUTADA")
        result["execution"] = {key: response.get(key) for key in
                               ("ticket", "order", "deal", "volume", "price", "sl", "tp", "detail")}
        self.database.add_log(
            "INFO" if reconciled else "CRITICAL" if response.get("unknown")
            or response.get("position_may_remain") or response.get("ok") else "WARN",
            f"S/R DEMO {symbol} {side}: {response.get('detail', 'sem detalhe')}")
        if response.get("unknown") or response.get("position_may_remain") or (
                response.get("ok") and not reconciled):
            self.stop()
