from __future__ import annotations

import threading
from datetime import datetime, timezone
from datetime import time as wall_time
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .config import MT5_SYMBOL_PATTERN
from .db import Database
from .strategy_rules import (
    STRATEGY_TYPES,
    broker_swap_carry,
    cross_sectional_currency_momentum,
    time_series_momentum,
    weekend_gap_reversal,
)
from .trading.ports import TradingPort

ENGINE_CONFIRMATION = "INICIAR MOTOR SOMENTE DEMO"
REAL_ENGINE_CONFIRMATION = "AUTORIZO MOTOR EM CONTA REAL"
ORB_STRATEGY_NAME = "Rompimento da faixa de abertura de Londres (ORB FX)"
ALLOWED_ZONES = {"Europe/London", "America/New_York"}


class ExecutionEngine:
    """Fail-closed declarative strategy engine for demo execution or observation."""

    def __init__(self, database: Database, gateway: TradingPort) -> None:
        self.database = database
        self.gateway = gateway
        saved = database.get_engine_runtime()
        self.config: dict[str, Any] = saved["config"]
        self.state: dict[str, Any] = saved["state"] or {
            "running": False, "mode": "parado", "phase": "parado",
            "detail": "Configure uma estratégia compatível e inicie o monitoramento.",
            "last_signal": None, "last_event_at": None,
        }
        # Restart never resumes trading. A fresh, explicit start is required.
        self.state.update(running=False, mode="parado", phase="parado",
                          detail="Motor parado após reinício; inicie novamente com confirmação.")
        self._lock = threading.RLock()
        self._service_thread: threading.Thread | None = None
        self._shutdown = threading.Event()
        self.gateway.disarm_order_engine("strategy")
        self._persist()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"config": dict(self.config), "state": dict(self.state),
                    "supported_strategy": ORB_STRATEGY_NAME,
                    "supported_strategies": list(STRATEGY_TYPES),
                    "demo_confirmation_required": ENGINE_CONFIRMATION,
                    "real_confirmation_required": REAL_ENGINE_CONFIRMATION}

    def configure(self, payload: dict[str, Any], strategies: list[dict[str, Any]]) -> dict[str, Any]:
        try:
            strategy_id = int(payload.get("strategy_id"))
            raw_symbols = payload.get("symbols", payload.get("symbol", ""))
            symbols = list(dict.fromkeys(part.strip() for part in str(raw_symbols).split(",") if part.strip()))
            symbol = symbols[0] if symbols else ""
            zone_name = str(payload.get("timezone", ""))
            session_open = wall_time.fromisoformat(str(payload.get("session_open", "08:00")))
            trade_end = wall_time.fromisoformat(str(payload.get("trade_end", "11:00")))
            range_minutes = int(payload.get("range_minutes", 15))
            risk_pct = float(payload.get("risk_per_trade_pct"))
            daily_loss_pct = float(payload.get("daily_loss_limit_pct"))
            reward_risk = float(payload.get("reward_risk"))
            lookback_days = int(payload.get("lookback_days", 20))
            gap_atr_multiple = float(payload.get("gap_atr_multiple", 1.5))
        except (TypeError, ValueError):
            return {"ok": False, "detail": "Preencha estratégia, ativo, sessão, faixa e limites com valores válidos."}
        strategy = next((item for item in strategies if item["id"] == strategy_id), None)
        if (not strategy or strategy.get("source_type") != "description"
                or strategy["name"] not in STRATEGY_TYPES):
            return {"ok": False, "detail": "Essa estratégia ainda não tem uma regra executável neste motor."}
        strategy_type = STRATEGY_TYPES[strategy["name"]]
        if strategy_type == "weekend_gap_reversal" and len(symbols) != 1:
            return {"ok": False, "detail": "Reversão de gap aceita somente um par FX por vez."}
        if (not symbols or len(symbols) > 12
                or any(not MT5_SYMBOL_PATTERN.fullmatch(item) for item in symbols)):
            return {"ok": False, "detail": "Informe de 1 a 12 nomes de ativos MT5 válidos, separados por vírgula."}
        if strategy_type == "opening_range_breakout" and len(symbols) != 1:
            return {"ok": False, "detail": "A estratégia ORB aceita somente um ativo."}
        if strategy_type == "cross_sectional_momentum" and len(symbols) < 3:
            return {"ok": False, "detail": "Momentum cross-sectional exige pelo menos três pares de moedas conectados."}
        if strategy_type == "broker_swap_carry" and len(symbols) != 1:
            return {"ok": False, "detail": "Carry por swap aceita um ativo por vez para não comparar swaps de contratos diferentes."}
        if zone_name not in ALLOWED_ZONES:
            return {"ok": False, "detail": "Escolha Europe/London ou America/New_York para tratar o horário de verão."}
        try:
            ZoneInfo(zone_name)
        except ZoneInfoNotFoundError:
            return {"ok": False, "detail": "Fuso horário indisponível neste Python."}
        range_end_minutes = session_open.hour * 60 + session_open.minute + range_minutes
        end_minutes = trade_end.hour * 60 + trade_end.minute
        if strategy_type == "opening_range_breakout" and (
                range_minutes < 5 or range_minutes > 60 or end_minutes <= range_end_minutes):
            return {"ok": False, "detail": "A faixa deve ter 5–60 minutos e terminar antes do fim da janela de entrada."}
        if not (2 <= lookback_days <= 252 and 0.5 <= gap_atr_multiple <= 5.0):
            return {"ok": False, "detail": "Lookback permitido: 2–252 barras D1; gap: 0,5–5 ATR."}
        if strategy_type == "weekend_gap_reversal" and zone_name != "America/New_York":
            return {"ok": False, "detail": "A regra de reabertura semanal está definida em America/New_York."}
        if not (0.01 <= risk_pct <= 0.25 and 0.1 <= daily_loss_pct <= 1.0 and 0.5 <= reward_risk <= 3.0):
            return {"ok": False, "detail": "Limites permitidos: risco/operação 0,01–0,25%, perda diária 0,1–1% e alvo 0,5–3R."}
        config = {"strategy_id": strategy_id, "strategy_name": strategy["name"],
                  "strategy_type": strategy_type, "symbol": symbol, "symbols": symbols,
                  "timezone": zone_name, "session_open": session_open.strftime("%H:%M"),
                  "range_minutes": range_minutes, "trade_end": trade_end.strftime("%H:%M"),
                  "risk_per_trade_pct": risk_pct, "daily_loss_limit_pct": daily_loss_pct,
                  "reward_risk": reward_risk, "lookback_days": lookback_days,
                  "gap_atr_multiple": gap_atr_multiple, "max_volume": 0.01}
        with self._lock:
            was_running = bool(self.state.get("running"))
            self.state.update(running=False, mode="parado", phase="parado",
                              detail="Configuração salva; inicie o motor quando estiver pronto.")
            self.gateway.disarm_order_engine("strategy")
            self.config = config
            if was_running:
                self.state["detail"] = "Motor parado porque a configuração foi alterada."
            self._persist()
        return {"ok": True, "detail": "Configuração salva. Limites são tetos de segurança, não promessa de risco realizado."}

    def start(self, mode: str, confirmation: str, strategies: list[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            if self.state.get("running"):
                return {"ok": False, "detail": "Motor já iniciado; pare-o antes de alterar o modo."}
            if getattr(self.gateway, "analyst_engine_armed", False):
                return {"ok": False, "detail": "O Analista de mercado está armado para DEMO; pare-o antes de iniciar este motor."}
            if not self.config:
                return {"ok": False, "detail": "Configure primeiro uma estratégia compatível."}
            strategy = next((item for item in strategies if item["id"] == self.config.get("strategy_id")), None)
            if (not strategy or strategy.get("source_type") != "description"
                    or strategy.get("name") not in STRATEGY_TYPES):
                return {"ok": False, "detail": "Esta estratégia ainda não possui regra declarativa compatível; traduza o código importado e valide-o antes de operar."}
            if strategy.get("status") != "approved":
                return {"ok": False, "detail": "A estratégia precisa ser aprovada manualmente para estudo demo antes de iniciar."}
            if mode not in {"observacao", "demo", "real"}:
                return {"ok": False, "detail": "Modo inválido."}
            terminal = self.gateway.state()
            account = terminal.get("account") or {}
            if not terminal.get("connected") or not account:
                return {"ok": False, "detail": "Conecte o MT5 antes de iniciar o motor."}
            if mode == "demo":
                if confirmation != ENGINE_CONFIRMATION:
                    return {"ok": False, "detail": f"Digite exatamente: {ENGINE_CONFIRMATION}. Nenhuma ordem foi enviada."}
                if account.get("mode") != "DEMO":
                    return {"ok": False, "detail": "Este armamento exige uma conta DEMO conectada."}
                if (not terminal.get("terminal", {}).get("trade_allowed")
                        or not account.get("trade_allowed") or not account.get("trade_expert")):
                    return {"ok": False, "detail": "Ative a negociação no terminal MT5 antes de iniciar."}
            if mode == "real":
                if confirmation != REAL_ENGINE_CONFIRMATION:
                    return {"ok": False, "detail": f"Digite exatamente: {REAL_ENGINE_CONFIRMATION}. Nenhuma ordem foi enviada."}
                if account.get("mode") != "REAL":
                    return {"ok": False, "detail": "A autorização REAL exige conta REAL conectada; CONTEST não é aceita."}
                if (not terminal.get("terminal", {}).get("trade_allowed")
                        or not account.get("trade_allowed") or not account.get("trade_expert")):
                    return {"ok": False, "detail": "Ative negociação algorítmica no terminal e na conta antes de iniciar."}
            fingerprint = f"{account.get('login')}@{account.get('server')}"
            if mode in {"demo", "real"} and not self.gateway.arm_order_engine(
                    "strategy", account["mode"], fingerprint):
                return {"ok": False, "detail": "Outro motor já está armado ou a conta não corresponde; pare-o antes de iniciar."}
            now_local = datetime.now(ZoneInfo(self.config["timezone"]))
            persisted_day = self.state.get("risk_day")
            persisted_account = self.state.get("account_fingerprint")
            if persisted_day != now_local.date().isoformat() or persisted_account != fingerprint:
                self.state["risk_day"] = now_local.date().isoformat()
                self.state["day_start_equity"] = float(account.get("equity", 0))
                self.state["last_attempt_day"] = None
            self.state.update(running=True, mode=mode, phase="inicializando",
                              detail="Motor iniciado; aguardando dados e condições da regra selecionada.",
                              account_fingerprint=fingerprint, started_at=datetime.now(timezone.utc).isoformat())
            self._persist()
        return {"ok": True, "detail": "Motor iniciado em " + ("OBSERVAÇÃO, sem ordens" if mode == "observacao" else f"{mode.upper()}, envio automático habilitado até parar o motor") + "."}

    def stop(self, reason: str = "Parado manualmente; posições abertas permanecem no MT5 com os stops enviados.") -> dict[str, Any]:
        with self._lock:
            self.state.update(running=False, mode="parado", phase="parado", detail=reason)
            self.gateway.disarm_order_engine("strategy")
            self._persist()
        self.database.add_log("WARN", f"Motor de estratégias parado: {reason}")
        return {"ok": True, "detail": reason}

    def start_service(self) -> None:
        if self._service_thread and self._service_thread.is_alive():
            return
        self._shutdown.clear()
        self._service_thread = threading.Thread(target=self._service_loop, name="scalperlab-strategy-engine", daemon=True)
        self._service_thread.start()

    def shutdown(self) -> None:
        self.stop("Aplicativo encerrado; confirme novamente após reiniciar.")
        self._shutdown.set()
        if self._service_thread:
            self._service_thread.join(timeout=5)

    def _service_loop(self) -> None:
        while not self._shutdown.is_set():
            with self._lock:
                active = bool(self.state.get("running"))
            if active:
                try:
                    self._evaluate()
                except Exception as exc:
                    self.stop(f"Falha interna segura ({type(exc).__name__}); verifique o MT5 antes de reiniciar.")
                    self.database.add_log("CRITICAL", f"Motor interrompido após falha segura: {type(exc).__name__}")
            self._shutdown.wait(3)

    def _evaluate(self) -> None:
        with self._lock:
            if not self.state.get("running"):
                return
            config = dict(self.config)
            mode = self.state["mode"]
        terminal = self.gateway.state()
        account = terminal.get("account") or {}
        fingerprint = f"{account.get('login')}@{account.get('server')}"
        if not terminal.get("connected") or fingerprint != self.state.get("account_fingerprint"):
            self.stop("Conexão/identidade MT5 mudou. Motor interrompido; nenhuma nova ordem será tentada.")
            self.database.add_log("CRITICAL", "Motor interrompido por perda ou troca da conexão/conta MT5.")
            return
        if mode in {"demo", "real"} and (not terminal.get("terminal", {}).get("trade_allowed")
                or not account.get("trade_allowed") or not account.get("trade_expert")):
            self.stop("Negociação desabilitada no terminal MT5. Motor interrompido antes de nova ordem.")
            return
        expected_mode = {"demo": "DEMO", "real": "REAL"}.get(mode)
        if expected_mode and account.get("mode") != expected_mode:
            self.stop(f"Conta mudou; execução {mode.upper()} interrompida. Confirme novamente na conta autorizada.")
            return
        equity = float(account.get("equity", 0))
        risk_day = datetime.now(ZoneInfo(config["timezone"])).date().isoformat()
        if self.state.get("risk_day") != risk_day:
            with self._lock:
                self.state["risk_day"] = risk_day
                self.state["day_start_equity"] = equity
                self._persist()
        baseline = float(self.state.get("day_start_equity", equity))
        loss_limit = baseline * config["daily_loss_limit_pct"] / 100.0
        if baseline - equity >= loss_limit:
            self.stop("Limite diário de perda atingido. Nenhuma nova entrada será enviada; verifique posições abertas no MT5.")
            self.database.add_log("CRITICAL", "Motor parado: limite de perda diária detectado pela variação de equity.")
            return
        strategy_type = config["strategy_type"]
        markets: dict[str, dict[str, Any]] = {}
        if strategy_type == "opening_range_breakout":
            data = self.gateway.strategy_market_data(config["symbol"], 2400, "M1")
            if not data.get("ok"):
                self._set_phase("indisponivel", data.get("detail", "Dados MT5 indisponíveis."))
                return
            markets[config["symbol"]] = data
            signal = self._opening_range_signal(data["bars"], config)
        elif strategy_type == "weekend_gap_reversal":
            symbol = config["symbol"]
            intraday = self.gateway.strategy_market_data(symbol, 12000, "M1")
            daily = self.gateway.strategy_market_data(symbol, 80, "D1")
            failed = intraday if not intraday.get("ok") else daily if not daily.get("ok") else None
            if failed:
                self._set_phase("indisponivel", failed.get("detail", "Dados MT5 indisponíveis."))
                return
            base_currency = str(intraday.get("contract", {}).get("currency_base", ""))
            quote_currency = str(intraday.get("contract", {}).get("currency_profit", ""))
            if not (len(base_currency) == 3 and base_currency.isalpha()
                    and len(quote_currency) == 3 and quote_currency.isalpha()):
                self._set_phase("sinal_bloqueado", "A regra de gap aceita somente contratos FX com moedas-base e cotada identificadas.")
                return
            markets[symbol] = intraday
            signal = weekend_gap_reversal(intraday["bars"], daily["bars"],
                                           now=datetime.now(timezone.utc),
                                           timezone_name=config["timezone"],
                                           gap_atr_multiple=config["gap_atr_multiple"],
                                           reward_risk=config["reward_risk"])
        elif strategy_type == "cross_sectional_momentum":
            failed = None
            for symbol in config["symbols"]:
                market = self.gateway.strategy_market_data(symbol, config["lookback_days"] + 20, "D1")
                if not market.get("ok"):
                    failed = market
                    break
                markets[symbol] = market
            if failed:
                self._set_phase("indisponivel", failed.get("detail", "D1 indisponível em um dos pares."))
                return
            signal = cross_sectional_currency_momentum(markets, config["lookback_days"])
        elif strategy_type == "time_series_momentum":
            symbol = config["symbol"]
            data = self.gateway.strategy_market_data(symbol, config["lookback_days"] + 20, "D1")
            if not data.get("ok"):
                self._set_phase("indisponivel", data.get("detail", "D1 indisponível."))
                return
            markets[symbol] = data
            signal = time_series_momentum(data["bars"], config["lookback_days"])
        elif strategy_type == "broker_swap_carry":
            symbol = config["symbol"]
            data = self.gateway.strategy_market_data(symbol, 80, "D1")
            if not data.get("ok"):
                self._set_phase("indisponivel", data.get("detail", "D1 indisponível."))
                return
            markets[symbol] = data
            signal = broker_swap_carry(data)
        else:
            self._set_phase("indisponivel", "Tipo de estratégia sem executor registrado.")
            return
        if signal.get("phase") != "sinal":
            self._set_phase(signal.get("phase", "monitorando"), signal.get("detail", "Aguardando faixa/rompimento."))
            return
        attempt_key = signal.get("session_key") or signal.get("session_day") or datetime.now(
            ZoneInfo(config["timezone"])).date().isoformat()
        if strategy_type in {"time_series_momentum", "cross_sectional_momentum", "broker_swap_carry"}:
            # D1 rules consume each closed bar at most once, rather than
            # reopening on every service cycle while the same trend persists.
            reference_symbol = signal.get("symbol", config["symbol"])
            reference = markets.get(reference_symbol) or next(iter(markets.values()), None)
            if strategy_type == "cross_sectional_momentum" and markets:
                latest_closed_bar = max(market["bars"][-1]["time"] for market in markets.values() if market.get("bars"))
            else:
                latest_closed_bar = reference["bars"][-1]["time"] if reference and reference.get("bars") else None
            if latest_closed_bar is not None:
                attempt_key = f"{attempt_key}:{latest_closed_bar}"
        if self.state.get("last_attempt_key", self.state.get("last_attempt_day")) == attempt_key:
            self._set_phase("entrada_usada", "Já houve uma tentativa para esta sessão/candle diário; sem nova ordem até a próxima janela.")
            return
        positions = self.gateway.positions()
        if not positions.get("available"):
            self._set_phase("indisponivel", positions.get("detail", "Posições indisponíveis; sinal bloqueado."))
            return
        if positions.get("items"):
            self._set_phase("bloqueado_posicao", "Há posição aberta na conta. O motor não vai interferir nem abrir outra.")
            return
        symbol = signal.get("symbol", config["symbol"])
        market = markets.get(symbol)
        if not market:
            self._set_phase("indisponivel", "O símbolo do sinal não pertence aos dados carregados; ordem bloqueada.")
            return
        contract = market["contract"]
        tick_data = self.gateway.current_tick(symbol)
        if not tick_data.get("ok"):
            self._set_phase("indisponivel", tick_data.get("detail", "Cotação indisponível."))
            return
        side = signal["side"]
        entry = tick_data["ask"] if side == "BUY" else tick_data["bid"]
        point = contract["point"]
        if strategy_type == "opening_range_breakout":
            stop = signal["low"] - point if side == "BUY" else signal["high"] + point
            risk_distance = abs(entry - stop)
            target = entry + risk_distance * config["reward_risk"] if side == "BUY" else entry - risk_distance * config["reward_risk"]
        else:
            risk_distance = float(signal["stop_distance"])
            stop = entry - risk_distance if side == "BUY" else entry + risk_distance
            target = signal.get("target_price")
            if target is None:
                target = entry + risk_distance * config["reward_risk"] if side == "BUY" else entry - risk_distance * config["reward_risk"]
        minimum_stops = max(contract["trade_stops_level"], 1) * point
        if risk_distance <= minimum_stops:
            self._set_phase("sinal_bloqueado", "Stop calculado menor que o mínimo do símbolo; sinal descartado.")
            return
        digits = contract["digits"]
        stop, target = round(stop, digits), round(target, digits)
        risk_cash = equity * config["risk_per_trade_pct"] / 100.0
        sizing = self.gateway.risk_volume(symbol, side, entry, stop, risk_cash, config["max_volume"])
        if not sizing.get("ok"):
            self._set_phase("sinal_bloqueado", sizing.get("detail", "Dimensionamento recusado."))
            return
        event = {"strategy": config["strategy_name"], "side": side, "symbol": symbol,
                 "time": signal.get("bar_time", datetime.now(timezone.utc).isoformat()),
                 "signal_value": signal.get("signal_value"), "rule_detail": signal.get("detail"),
                 "range_high": signal.get("high"), "range_low": signal.get("low"),
                 "entry": entry, "stop": stop, "target": target, "volume": sizing["volume"],
                 "estimated_loss": sizing["estimated_loss"], "session_key": attempt_key}
        with self._lock:
            # Persist the one-shot claim before any external trading request; never blindly retry.
            self.state["last_attempt_key"] = attempt_key
            self.state["last_attempt_day"] = attempt_key
            self.state["last_signal"] = event
            self.state["phase"] = "sinal_observado" if mode == "observacao" else "enviando"
            self.state["detail"] = "Sinal detectado; sem ordem enviada (modo observação)." if mode == "observacao" else "Sinal detectado; validando pedido no MT5."
            self._persist()
        if mode == "observacao":
            self.database.add_log("INFO", f"Sinal {config['strategy_name']} observado: {side} {symbol} (sem ordem).")
            self._set_phase("sinal_observado", "Sinal anotado em OBSERVAÇÃO; nenhuma ordem foi enviada.")
            return
        with self._lock:
            if not self.state.get("running") or self.state.get("mode") != mode:
                return
            # Serialize the external order request with stop/reconfigure, so a stop
            # cannot race with an order that has not yet been submitted.
            send_order = (self.gateway.send_real_strategy_order if mode == "real"
                          else self.gateway.send_demo_strategy_order)
            result = send_order(symbol, side, sizing["volume"], stop, target, config["strategy_id"],
                                expected_account_fingerprint=self.state.get("account_fingerprint"),
                                risk_cash=risk_cash)
            self.state["last_signal"] = {**event, "execution": result}
            if result.get("unknown"):
                self.state.update(running=False, mode="parado", phase="resultado_desconhecido",
                                  detail=result["detail"])
                self.gateway.disarm_order_engine("strategy")
            elif result.get("blocked"):
                self.state.update(running=False, mode="parado", phase="parado",
                                  detail=result["detail"])
                self.gateway.disarm_order_engine("strategy")
            elif result.get("ok"):
                self.state.update(phase="ordem_confirmada", detail=result["detail"])
            else:
                self.state.update(phase="ordem_recusada", detail=result["detail"])
            self._persist()
        self.database.add_log("INFO" if result.get("ok") else "CRITICAL" if result.get("unknown") else "WARN",
                              f"Execução {config['strategy_name']} {side} {symbol}: {result.get('detail')}")

    @staticmethod
    def _opening_range_signal(bars: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        zone = ZoneInfo(config["timezone"])
        now = datetime.now(zone)
        session_day = now.date()
        opening = datetime.combine(session_day, wall_time.fromisoformat(config["session_open"]), tzinfo=zone)
        range_end = opening.timestamp() + config["range_minutes"] * 60
        trade_end = datetime.combine(session_day, wall_time.fromisoformat(config["trade_end"]), tzinfo=zone)
        local_bars = []
        for bar in bars:
            moment = datetime.fromtimestamp(bar["time"], timezone.utc).astimezone(zone)
            if moment.date() == session_day:
                local_bars.append((moment, bar))
        range_bars = [bar for moment, bar in local_bars if opening.timestamp() <= moment.timestamp() < range_end]
        if now < datetime.fromtimestamp(range_end, zone):
            return {"phase": "aguardando_faixa", "detail": "Aguardando conclusão da faixa inicial da sessão."}
        if len(range_bars) != config["range_minutes"]:
            return {"phase": "dados_incompletos", "detail": "Não há barras suficientes para a faixa de abertura; nenhuma ordem será considerada."}
        high = max(bar["high"] for bar in range_bars)
        low = min(bar["low"] for bar in range_bars)
        if now.timestamp() >= trade_end.timestamp():
            return {"phase": "sessao_encerrada", "detail": "Janela de entrada da sessão encerrada."}
        eligible = [(moment, bar) for moment, bar in local_bars
                    if range_end <= moment.timestamp() and moment.timestamp() < now.timestamp()]
        if len(eligible) < 2:
            return {"phase": "monitorando", "detail": "Faixa calculada; aguardando rompimento confirmado por fechamento M1."}
        (previous_time, previous), (last_time, last) = eligible[-2:]
        if last_time.timestamp() >= trade_end.timestamp():
            return {"phase": "sessao_encerrada", "detail": "Janela de entrada da sessão encerrada."}
        if now.timestamp() - last_time.timestamp() > 120 or last_time.timestamp() - previous_time.timestamp() > 90:
            return {"phase": "dados_atrasados", "detail": "Barras M1 atrasadas ou incompletas; sinal bloqueado."}
        if previous["close"] <= high and last["close"] > high:
            return {"phase": "sinal", "side": "BUY", "high": high, "low": low,
                    "bar_time": last_time.isoformat(), "session_day": session_day.isoformat()}
        if previous["close"] >= low and last["close"] < low:
            return {"phase": "sinal", "side": "SELL", "high": high, "low": low,
                    "bar_time": last_time.isoformat(), "session_day": session_day.isoformat()}
        return {"phase": "monitorando", "detail": "Faixa calculada; aguardando rompimento confirmado por fechamento M1."}

    def _set_phase(self, phase: str, detail: str) -> None:
        with self._lock:
            if self.state.get("running") and (self.state.get("phase") != phase or self.state.get("detail") != detail):
                self.state.update(phase=phase, detail=detail)
                self._persist()

    def _persist(self) -> None:
        self.database.save_engine_runtime(self.config, self.state)
