from __future__ import annotations

import copy
import math
import threading
import time
from datetime import datetime, timezone
from statistics import median
from typing import Any

from .config import MT5_SYMBOL_PATTERN
from .mt5_time import (MAX_FUTURE_TIME_SKEW_SECONDS, MAX_TICK_AGE_SECONDS,
                       MT5_TIMEFRAME_SECONDS)
from .trading.ports import TradingPort

TIMEFRAMES_SECONDS = MT5_TIMEFRAME_SECONDS
SYMBOL_PATTERN = MT5_SYMBOL_PATTERN
ANALYSIS_BASIS = "technical_quantitative"
ANALYSIS_BASIS_LABEL = "Técnica + quantitativa"


def _sma(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _true_ranges(bars: list[dict[str, Any]]) -> list[float]:
    result: list[float] = []
    for previous, current in zip(bars[:-1], bars[1:], strict=True):
        result.append(max(current["high"] - current["low"],
                          abs(current["high"] - previous["close"]),
                          abs(current["low"] - previous["close"])))
    return result


def _rsi(closes: list[float], period: int = 14) -> float | None:
    changes = [right - left for left, right in zip(closes[:-1], closes[1:], strict=True)]
    if len(changes) < period:
        return None
    window = changes[-period:]
    gains = sum(max(value, 0.0) for value in window) / period
    losses = sum(max(-value, 0.0) for value in window) / period
    if losses == 0:
        return 100.0 if gains > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + gains / losses)


def _swings(bars: list[dict[str, Any]], width: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    # A pivot is used only after `width` later closed bars confirm it.
    for index in range(width, len(bars) - width):
        high = bars[index]["high"]
        low = bars[index]["low"]
        neighbors = [bars[pos] for pos in range(index - width, index + width + 1) if pos != index]
        if all(high > item["high"] for item in neighbors):
            highs.append((index, high))
        if all(low < item["low"] for item in neighbors):
            lows.append((index, low))
    return highs, lows


def _bias_label(value: float | None) -> str:
    if value is None or not math.isfinite(value) or abs(value) < 1e-12:
        return "neutro"
    return "alta" if value > 0 else "baixa"


def analyze_market(symbol: str, timeframe: str, bars: list[dict[str, Any]],
                   contract: dict[str, Any], tick: dict[str, Any] | None = None,
                   fundamental: dict[str, Any] | None = None,
                   *, now_epoch: float | None = None) -> dict[str, Any]:
    """Analyze closed bars and derive an auditable experimental pullback signal."""
    timeframe = timeframe.upper()
    if timeframe not in TIMEFRAMES_SECONDS:
        raise ValueError("Timeframe MT5 não suportado.")
    if not SYMBOL_PATTERN.fullmatch(symbol.upper()):
        raise ValueError("Nome de ativo inválido.")

    ordered = sorted(bars, key=lambda row: int(row.get("time", 0)))
    if len(ordered) < 60:
        return _insufficient(symbol.upper(), timeframe, len(ordered),
                             "Histórico insuficiente; são necessárias pelo menos 60 barras fechadas.")
    required = ("time", "open", "high", "low", "close")
    clean: list[dict[str, Any]] = []
    last_time = 0
    for row in ordered:
        if any(key not in row for key in required):
            return _insufficient(symbol.upper(), timeframe, len(ordered), "Há barras sem campos OHLC completos.")
        values = [float(row[key]) for key in ("open", "high", "low", "close")]
        if not all(math.isfinite(value) and value > 0 for value in values):
            return _insufficient(symbol.upper(), timeframe, len(ordered), "Há preços ausentes, não finitos ou inválidos.")
        opened, high, low, close = values
        if high < max(opened, close, low) or low > min(opened, close, high):
            return _insufficient(symbol.upper(), timeframe, len(ordered), "Uma barra OHLC tem máximas/mínimas inconsistentes.")
        stamp = int(row["time"])
        if stamp <= last_time:
            return _insufficient(symbol.upper(), timeframe, len(ordered), "Há horários repetidos ou fora de ordem no histórico.")
        last_time = stamp
        clean.append({**row, "time": stamp, "open": opened, "high": high, "low": low, "close": close})

    reference_epoch = time.time() if now_epoch is None else float(now_epoch)
    if clean[-1]["time"] > reference_epoch + MAX_FUTURE_TIME_SKEW_SECONDS:
        return _insufficient(symbol.upper(), timeframe, len(clean),
                             "Timestamp do último candle está no futuro; "
                             "análise bloqueada até validar UTC.")

    closes = [row["close"] for row in clean]
    ranges = _true_ranges(clean)
    atr14 = sum(ranges[-14:]) / 14 if len(ranges) >= 14 else None
    sma21, sma50 = _sma(closes, 21), _sma(closes, 50)
    sma21_prev = _sma(closes[:-5], 21) if len(closes) > 25 else None
    slope21 = (sma21 - sma21_prev) if sma21 is not None and sma21_prev is not None else None
    rsi14 = _rsi(closes, 14)

    mean20 = _sma(closes, 20)
    std20 = None
    if mean20 is not None:
        std20 = math.sqrt(sum((value - mean20) ** 2 for value in closes[-20:]) / 20)
    bb_position = ((closes[-1] - (mean20 - 2 * std20)) / (4 * std20)
                   if mean20 is not None and std20 and std20 > 0 else None)

    swing_highs, swing_lows = _swings(clean)
    higher_highs = len(swing_highs) >= 2 and swing_highs[-1][1] > swing_highs[-2][1]
    higher_lows = len(swing_lows) >= 2 and swing_lows[-1][1] > swing_lows[-2][1]
    lower_highs = len(swing_highs) >= 2 and swing_highs[-1][1] < swing_highs[-2][1]
    lower_lows = len(swing_lows) >= 2 and swing_lows[-1][1] < swing_lows[-2][1]
    if higher_highs and higher_lows:
        structure = "alta"
    elif lower_highs and lower_lows:
        structure = "baixa"
    else:
        structure = "indefinida/lateral"

    previous, latest = clean[-2], clean[-1]
    outside_bar = latest["high"] > previous["high"] and latest["low"] < previous["low"]
    candle_range = latest["high"] - latest["low"]
    body_fraction = abs(latest["close"] - latest["open"]) / candle_range if candle_range > 0 else None
    candle_direction = "alta" if latest["close"] > latest["open"] else "baixa" if latest["close"] < latest["open"] else "neutra"
    distance_atr = abs(latest["close"] - sma21) / atr14 if sma21 is not None and atr14 else None

    returns = [right / left - 1.0 for left, right in
               zip(closes[-21:-1], closes[-20:], strict=True) if left > 0]
    momentum20 = closes[-1] / closes[-21] - 1.0 if closes[-21] > 0 else None
    return_volatility = (math.sqrt(sum(value * value for value in returns) / len(returns))
                         if returns else None)
    rolling_atr: list[float] = []
    for end in range(max(14, len(ranges) - 79), len(ranges) + 1):
        window = ranges[max(0, end - 14):end]
        if len(window) == 14:
            rolling_atr.append(sum(window) / 14)
    atr_median = median(rolling_atr) if rolling_atr else None
    volatility_ratio = atr14 / atr_median if atr14 and atr_median and atr_median > 0 else None

    support = swing_lows[-1][1] if swing_lows else None
    resistance = swing_highs[-1][1] if swing_highs else None
    tick_volume_ratio = None
    volumes = [float(row.get("tick_volume", 0) or 0) for row in clean]
    if len(volumes) >= 21 and sum(volumes[-21:-1]) > 0:
        tick_volume_ratio = volumes[-1] / (sum(volumes[-21:-1]) / 20)

    technical_bias = ("alta" if structure == "alta" and sma21 is not None and sma50 is not None
                      and sma21 > sma50 and (slope21 or 0) > 0 else
                      "baixa" if structure == "baixa" and sma21 is not None and sma50 is not None
                      and sma21 < sma50 and (slope21 or 0) < 0 else "neutro")
    quant_bias = _bias_label(momentum20)
    aligned = technical_bias == quant_bias and technical_bias != "neutro"
    aligned_bias = technical_bias if aligned else "sem_confluência"

    spread_points = None
    spread_atr = None
    if tick and contract.get("point"):
        spread_points = (float(tick["ask"]) - float(tick["bid"])) / float(contract["point"])
        spread_atr = ((float(tick["ask"]) - float(tick["bid"])) / atr14
                      if atr14 and atr14 > 0 else None)

    reasons: list[str] = []
    direction = "BUY" if aligned_bias == "alta" else "SELL" if aligned_bias == "baixa" else None
    pullback = False
    stop = target = None
    if direction and sma21 is not None and atr14 and atr14 > 0:
        strong_body = body_fraction is not None and body_fraction >= 0.55
        if direction == "BUY":
            pullback = (latest["low"] <= sma21 + 0.15 * atr14 and latest["close"] > sma21
                        and candle_direction == "alta" and strong_body
                        and latest["close"] >= latest["low"] + 0.75 * candle_range)
            if pullback and support is not None:
                stop = min(support, latest["low"]) - 0.1 * atr14
                target = latest["close"] + 1.5 * (latest["close"] - stop)
        else:
            pullback = (latest["high"] >= sma21 - 0.15 * atr14 and latest["close"] < sma21
                        and candle_direction == "baixa" and strong_body
                        and latest["close"] <= latest["high"] - 0.75 * candle_range)
            if pullback and resistance is not None:
                stop = max(resistance, latest["high"]) + 0.1 * atr14
                target = latest["close"] - 1.5 * (stop - latest["close"])
    spread_ok = spread_atr is not None and spread_atr <= 0.08
    if not aligned:
        reasons.append("Viés técnico e quantitativo não estão alinhados.")
    if not pullback:
        reasons.append("O candle fechado não confirmou retomada após pullback na SMA 21.")
    if direction and pullback and (stop is None or target is None or
            (direction == "BUY" and not stop < latest["close"] < target) or
            (direction == "SELL" and not target < latest["close"] < stop)):
        reasons.append("Não foi possível formar stop e alvo válidos a partir da estrutura confirmada.")
        pullback = False
    if not spread_ok:
        reasons.append("Spread ausente ou superior a 0,08 ATR; entrada bloqueada.")
    fundamental = fundamental or {
        "status": "unavailable", "bias": "unknown",
        "detail": "Sem feed estruturado de eventos, taxas e dados fundamentais compatíveis com a classe do ativo.",
        "events": [],
    }
    reasons.append("Base da regra: técnica + quantitativa. Dados fundamentais e calendário são informativos; não participam do gatilho de entrada.")
    eligible = bool(direction and pullback and spread_ok and stop is not None and target is not None)
    if eligible:
        reasons.insert(0, "Sinal experimental de pullback confirmado em candle fechado; sujeito às verificações de DEMO e risco.")
    action = ("CANDIDATO_COMPRA" if direction == "BUY" else "CANDIDATO_VENDA") if eligible else "AGUARDAR"
    return {
        "symbol": symbol.upper(), "timeframe": timeframe,
        "decision_basis": ANALYSIS_BASIS,
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "last_closed_bar_at": datetime.fromtimestamp(latest["time"], timezone.utc).isoformat(timespec="seconds"),
        "bars_used": len(clean),
        "technical": {
            "status": "available", "trend_structure": structure, "bias": technical_bias,
            "sma21": sma21, "sma50": sma50, "sma21_slope_5_bars": slope21,
            "atr14": atr14, "rsi14": rsi14, "bollinger_position_20_2sd": bb_position,
            "distance_to_sma21_atr": distance_atr,
            "latest_candle": {"direction": candle_direction, "outside_bar": outside_bar,
                              "body_fraction": body_fraction},
            "last_confirmed_support": support, "last_confirmed_resistance": resistance,
            "tick_volume_vs_20_bar_mean": tick_volume_ratio,
            "volume_note": "O MT5 fornece tick volume; em Forex OTC isso não representa volume centralizado.",
        },
        "quantitative": {
            "status": "available", "bias": quant_bias, "return_20_bars": momentum20,
            "rms_return_20_bars": return_volatility, "atr14_vs_recent_median": volatility_ratio,
            "technical_quant_alignment": aligned,
            "method_note": "Estatísticas descritivas de barras fechadas; não são probabilidade nem evidência de vantagem.",
        },
        "fundamental": fundamental,
        "decision": {"basis": ANALYSIS_BASIS, "basis_label": ANALYSIS_BASIS_LABEL,
                     "fundamental_required": False,
                     "action": action, "directional_context": aligned_bias,
                     "order_eligible": eligible, "signal_eligible": eligible,
                     "side": direction if eligible else None,
                     "entry_reference": latest["close"] if eligible else None,
                     "stop": stop if eligible else None, "target": target if eligible else None,
                     "risk_reward": 1.5 if eligible else None, "setup": "pullback_sma21_closed_candle",
                     "reasons": reasons},
        "contract": {key: contract.get(key) for key in (
            "digits", "point", "trade_tick_size", "trade_tick_value_profit", "trade_tick_value_loss",
            "trade_contract_size", "volume_min", "volume_max", "volume_step", "trade_stops_level",
            "currency_base", "currency_profit", "currency_margin", "trade_mode", "country", "sector")},
        "quote": {"spread_points": spread_points, "spread_to_atr": spread_atr,
                  "available": bool(tick)},
        "source_basis": ["BabyPips-forex.pdf", "Analise-Tecnica-dos-Mercados-Financeiros.pdf (trecho fornecido)",
                         "admin,+1231-5270-1-ED.pdf"],
    }


def _insufficient(symbol: str, timeframe: str, count: int, detail: str) -> dict[str, Any]:
    return {
        "symbol": symbol, "timeframe": timeframe, "decision_basis": ANALYSIS_BASIS,
        "analyzed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "bars_used": count, "technical": {"status": "unavailable", "detail": detail},
        "quantitative": {"status": "unavailable", "detail": detail},
        "fundamental": {"status": "unavailable", "bias": "unknown", "detail": "Análise bloqueada por dados insuficientes."},
        "decision": {"basis": ANALYSIS_BASIS, "basis_label": ANALYSIS_BASIS_LABEL,
                     "fundamental_required": False,
                     "action": "AGUARDAR", "directional_context": "indisponível",
                     "order_eligible": False, "signal_eligible": False,
                     "reasons": [detail, "Nenhuma ordem foi enviada."]},
    }


class MarketAnalystEngine:
    """Continuous market analysis with explicit observation and demo-execution modes."""

    def __init__(self, database: Any, gateway: TradingPort, interval_seconds: int = 30,
                 clock_service: Any | None = None, risk_settings=None) -> None:
        self.database = database
        self.gateway = gateway
        self.clock_service = clock_service
        self.risk_settings = risk_settings
        self.interval_seconds = max(15, int(interval_seconds))
        saved_config = database.get_analyst_profile()
        self.config: dict[str, Any] = saved_config if isinstance(saved_config, dict) else {}
        self.config.setdefault("symbols", [])
        self.config.setdefault("timeframe", "M15")
        self.config.setdefault("decision_basis", ANALYSIS_BASIS)
        self.config.setdefault("risk_per_trade_pct", 0.10)
        self.config.setdefault("daily_loss_limit_pct", 1.0)
        self.state: dict[str, Any] = {
            "running": False, "mode": "parado", "phase": "parado", "detail": "Configure ativo(s) para iniciar a análise.",
            "analyses": [], "last_cycle_at": None, "account_fingerprint": None,
            "risk_day": None, "day_start_equity": None, "attempted_signals": [],
        }
        self._lock = threading.RLock()
        self._cycle_lock = threading.RLock()
        self._shutdown = threading.Event()
        self._thread: threading.Thread | None = None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"config": {**copy.deepcopy(self.config), **(self.risk_settings.profile("analyst") if self.risk_settings else {})}, "state": copy.deepcopy(self.state),
                    "decision_basis": self.config.get("decision_basis", ANALYSIS_BASIS),
                    "interval_seconds": self.interval_seconds,
                    "timeframes": list(TIMEFRAMES_SECONDS),
                    "execution_mode_active": bool(
                        self.state.get("running") and self.state.get("mode") in {"demo", "real"})}

    def _clock_failure(self, account_fingerprint: str | None, *, fresh_measurement: bool = False) -> str | None:
        """Return a fail-closed reason unless the current terminal/account clock check is valid."""
        if self.clock_service is None:
            return "Verificação UTC indisponível no motor; nenhuma ordem será enviada."
        try:
            terminal_id = getattr(self.gateway, "terminal_id", None)
            clock_state = self.clock_service.snapshot()
            if (clock_state.get("status") != "synchronized"
                    or clock_state.get("mt5_status") != "verified"):
                return (clock_state.get("detail")
                        or "Validação UTC expirada ou incompleta; verifique o relógio antes de executar.")
            verifier = (self.clock_service.is_verified if fresh_measurement
                        else self.clock_service.is_currently_verified)
            if not verifier(terminal_id=terminal_id, account_fingerprint=account_fingerprint):
                return "A validação UTC deixou de ser válida para este terminal/conta; verifique novamente."
        except Exception:
            return "Não foi possível revalidar o relógio UTC; nenhuma ordem será enviada."
        return None

    def _suspend_for_clock(self, reason: str) -> None:
        detail = f"Execução suspensa por validação UTC expirada ou inválida: {reason} Nenhuma nova ordem será enviada; confira posições no MT5."
        self.stop(detail, phase="bloqueado_relogio")
        try:
            self.database.add_log("WARN", f"Analista: {detail}")
        except Exception:
            pass

    def configure(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_symbols = payload.get("symbols", payload.get("symbol", ""))
        if isinstance(raw_symbols, list):
            symbols = list(dict.fromkeys(part.strip() for part in raw_symbols
                                         if isinstance(part, str) and part.strip()))
        else:
            symbols = list(dict.fromkeys(part.strip() for part in str(raw_symbols).split(",") if part.strip()))
        timeframe = str(payload.get("timeframe", "M15")).strip().upper()
        decision_basis = str(payload.get("decision_basis", ANALYSIS_BASIS)).strip()
        if not symbols or len(symbols) > 12 or any(not SYMBOL_PATTERN.fullmatch(item) for item in symbols):
            return {"ok": False, "detail": "Informe de 1 a 12 símbolos válidos do Market Watch, separados por vírgula."}
        if timeframe not in TIMEFRAMES_SECONDS:
            return {"ok": False, "detail": "Timeframe MT5 inválido."}
        if decision_basis != ANALYSIS_BASIS:
            return {"ok": False, "detail": "Base indisponível. O único modo ativo é Técnica + quantitativa; três camadas aguardam dados fundamentais adequados."}
        with self._lock:
            if self.state.get("running"):
                return {"ok": False, "detail": "Pare o Analista antes de alterar o perfil; isso evita trocar os parâmetros durante um ciclo."}
            self.config = {"symbols": symbols, "timeframe": timeframe,
                           "decision_basis": decision_basis,
                           "risk_per_trade_pct": 0.10, "daily_loss_limit_pct": 1.0}
            self.state.update(phase="configurado", detail="Perfil salvo. A análise contínua ainda não começou.", analyses=[])
            self.database.save_analyst_profile(self.config)
        return {"ok": True, "detail": "Perfil salvo no modo Técnica + quantitativa. O calendário é informativo e não participa do gatilho."}

    def start(self, mode: str = "observacao", confirmation: str = "") -> dict[str, Any]:
        with self._lock:
            if self.state.get("running"):
                return {"ok": False, "detail": "Analista já iniciado; pare-o antes de alterar o modo."}
            if not self.config.get("symbols"):
                return {"ok": False, "detail": "Informe ao menos um símbolo antes de iniciar."}
            if self.config.get("decision_basis") != ANALYSIS_BASIS:
                return {"ok": False, "detail": "Base de decisão não suportada; salve novamente o perfil Técnica + quantitativa."}
        terminal = self.gateway.state()
        if not terminal.get("connected"):
            return {"ok": False, "detail": terminal.get("detail") or "Conecte o MT5 antes de iniciar a análise."}
        validation = self.gateway.validate_market_symbols(self.config.get("symbols", []))
        if not validation.get("available"):
            return {"ok": False, "detail": validation.get("detail") or "Não foi possível validar os símbolos no MT5."}
        if not validation.get("valid"):
            invalid = validation.get("invalid", [])
            details = "; ".join(
                f"{item['requested']}" + (f" (sugestões: {', '.join(item['suggestions'])})" if item.get("suggestions") else "")
                for item in invalid
            )
            return {"ok": False, "detail": f"Perfil não iniciado: símbolo(s) não encontrado(s) no Market Watch: {details}. Use os nomes exatos do broker."}
        account = terminal.get("account") or {}
        if mode not in {"observacao", "demo", "real"}:
            return {"ok": False, "detail": "Modo de operação inválido."}
        if mode in {"demo", "real"}:
            catalog = self.gateway.market_watch_catalog()
            if not catalog.get("available"):
                return {"ok": False, "detail": catalog.get("detail") or "Não foi possível consultar as permissões dos ativos no MT5."}
            contracts = {item.get("broker_symbol"): item for item in catalog.get("items", [])}
            not_tradable = [symbol for symbol in self.config.get("symbols", [])
                            if not contracts.get(symbol, {}).get("trade_enabled", False)]
            if not_tradable:
                return {"ok": False, "detail": "Execução exige ativos negociáveis pelo broker; ajuste a seleção: "
                        + ", ".join(not_tradable) + "."}
        if mode == "demo":
            if confirmation != "INICIAR ANALISTA SOMENTE DEMO":
                return {"ok": False, "detail": "Confirmação incorreta. Nenhuma ordem foi habilitada."}
            if (account.get("mode") != "DEMO" or not terminal.get("terminal", {}).get("trade_allowed")
                    or not account.get("trade_allowed") or not account.get("trade_expert")):
                return {"ok": False, "detail": "Envio disponível apenas em conta DEMO conectada e com negociação habilitada."}
        elif mode == "real":
            if confirmation != "AUTORIZO ANALISTA EM CONTA REAL":
                return {"ok": False, "detail": "Digite exatamente: AUTORIZO ANALISTA EM CONTA REAL. Nenhuma ordem foi enviada."}
            if (account.get("mode") != "REAL" or not terminal.get("terminal", {}).get("trade_allowed")
                    or not account.get("trade_allowed") or not account.get("trade_expert")):
                return {"ok": False, "detail": "Execução REAL exige conta REAL identificada e negociação habilitada no terminal."}
        elif mode != "observacao":
            return {"ok": False, "detail": "Modo inválido."}
        fingerprint = f"{account.get('login')}@{account.get('server')}"
        if self.risk_settings and mode in {"demo", "real"}:
            daily = self.risk_settings.daily_check(self.gateway, account)
            if not daily["ok"]:
                return daily
        if mode in {"demo", "real"}:
            clock_failure = self._clock_failure(fingerprint, fresh_measurement=True)
            if clock_failure:
                return {"ok": False, "detail": f"Execução bloqueada: {clock_failure}"}
        with self._lock:
            if mode in {"demo", "real"} and not self.gateway.arm_order_engine(
                    "analyst", account["mode"], fingerprint):
                return {"ok": False, "detail": "Outro motor de execução já está armado; pare-o antes de iniciar o Analista."}
            self.state.update(running=True, mode=mode, phase="inicializando",
                              decision_basis=ANALYSIS_BASIS,
                              account_fingerprint=fingerprint,
                              risk_day=datetime.now(timezone.utc).date().isoformat(),
                              day_start_equity=float(account.get("equity", 0) or 0),
                              attempted_signals=[],
                              detail=(f"Modo Técnica + quantitativa iniciado em {mode.upper()}; fundamental/calendário são informativos. Ordens dependem de sinal e preflight."
                                      if mode in {"demo", "real"} else "Modo Técnica + quantitativa iniciado em observação; não envia ordens."))
        return {"ok": True, "detail": "Analista Técnica + quantitativa iniciado em " + (f"{mode.upper()} com envio condicionado a sinal e limites" if mode in {"demo", "real"} else "observação, sem envio de ordens") + "."}

    def stop(self, reason: str | None = None, *, phase: str = "parado") -> dict[str, Any]:
        with self._lock:
            was_armed = self.state.get("mode") in {"demo", "real"}
            previous_mode = self.state.get("mode")
            self.state.update(running=False, mode="parado", phase=phase,
                              detail=reason or "Análise contínua parada; posições já abertas permanecem no MT5.")
            self.gateway.disarm_order_engine("analyst")
        # A mode change waits for any in-flight observation cycle to finish. Since
        # running is already false, that cycle cannot begin a new order submission.
        with self._cycle_lock:
            pass
        return {"ok": True, "detail": reason or (f"Análise/execução {previous_mode.upper()} parada; posições abertas permanecem no MT5." if was_armed else "Análise contínua parada.")}

    def start_service(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._shutdown.clear()
        self._thread = threading.Thread(target=self._service_loop, name="scalperlab-market-analyst", daemon=True)
        self._thread.start()

    def shutdown(self) -> None:
        self.stop()
        self._shutdown.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _service_loop(self) -> None:
        while not self._shutdown.is_set():
            with self._lock:
                running = self.state.get("running", False)
            if running:
                with self._cycle_lock:
                    with self._lock:
                        running = self.state.get("running", False)
                        mode = self.state.get("mode", "parado")
                        fingerprint = self.state.get("account_fingerprint")
                        config = (copy.deepcopy(self.config) if running else
                                  {"symbols": [], "timeframe": self.config.get("timeframe", "M15")})
                    if running and mode in {"demo", "real"}:
                        clock_failure = self._clock_failure(fingerprint)
                        if clock_failure:
                            self._suspend_for_clock(clock_failure)
                            config["symbols"] = []
                    results = []
                    for symbol in config.get("symbols", []):
                        if self._shutdown.is_set():
                            break
                        with self._lock:
                            if not self.state.get("running"):
                                break
                        try:
                            market = self.gateway.strategy_market_data(symbol, 300, config["timeframe"])
                            if not market.get("ok"):
                                results.append({"symbol": symbol, "timeframe": config["timeframe"],
                                                "decision": {"action": "AGUARDAR",
                                                             "directional_context": "indisponível", "order_eligible": False,
                                                             "reasons": [market.get("detail", "Dados indisponíveis.")]},
                                                "technical": {"status": "unavailable"},
                                                "quantitative": {"status": "unavailable"},
                                                "fundamental": {"status": "unavailable", "bias": "unknown"}})
                                continue
                            tick = self.gateway.current_tick(symbol)
                            fundamental = self.gateway.economic_calendar(symbol)
                            analysis = analyze_market(symbol, config["timeframe"], market["bars"],
                                                      market.get("contract", {}), tick if tick.get("ok") else None,
                                                      fundamental=fundamental)
                            analysis["time_normalization"] = market.get("time_normalization")
                            self._maybe_execute(symbol, analysis, market, tick)
                            results.append(analysis)
                        except Exception as exc:
                            results.append({"symbol": symbol, "timeframe": config["timeframe"],
                                            "decision": {"action": "AGUARDAR",
                                                         "directional_context": "indisponível", "order_eligible": False,
                                                         "reasons": [f"Falha segura ({type(exc).__name__}); nenhuma ordem foi enviada."]},
                                            "technical": {"status": "unavailable"},
                                            "quantitative": {"status": "unavailable"},
                                            "fundamental": {"status": "unavailable", "bias": "unknown"}})
                    with self._lock:
                        if results:
                            # Keep the final decision visible even when a clock failure,
                            # risk stop, or uncertain send disarms the analyst mid-cycle.
                            update = {
                                "analyses": results,
                                "last_cycle_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                            }
                            if self.state.get("running"):
                                update.update(
                                    phase="analisando",
                                    detail=f"Último ciclo concluído para {len(results)} símbolo(s); modo {self.state.get('mode')}.",
                                )
                            self.state.update(**update)
            self._shutdown.wait(self.interval_seconds)

    def _maybe_execute(self, symbol: str, analysis: dict[str, Any], market: dict[str, Any],
                       tick: dict[str, Any]) -> None:
        with self._lock:
            if not self.state.get("running") or self.state.get("mode") not in {"demo", "real"}:
                return
            if not analysis.get("decision", {}).get("order_eligible"):
                analysis["decision"]["execution_status"] = "SINAL_NAO_CONFIRMADO"
                return
            decision = analysis["decision"]
            key = f"{symbol}:{analysis.get('timeframe')}:{analysis.get('last_closed_bar_at')}"
            attempted = set(self.state.get("attempted_signals", []))
            if key in attempted:
                decision["execution_status"] = "SINAL_JA_PROCESSADO"
                return
            attempted.add(key)
            self.state["attempted_signals"] = list(attempted)[-500:]
            run_mode = self.state.get("mode")
            fingerprint = self.state.get("account_fingerprint")
            start_equity = float(self.state.get("day_start_equity") or 0)
        terminal = self.gateway.state()
        account = terminal.get("account") or {}
        current_fingerprint = f"{account.get('login')}@{account.get('server')}"
        expected_mode = "REAL" if run_mode == "real" else "DEMO"
        if (not terminal.get("connected") or account.get("mode") != expected_mode
                or current_fingerprint != fingerprint or not terminal.get("terminal", {}).get("trade_allowed")):
            decision["execution_status"] = "BLOQUEADO_CONTA_OU_TERMINAL"
            decision["reasons"].append(f"Conta {expected_mode}, identidade ou permissão do terminal mudou; envio cancelado.")
            return
        daily = self.risk_settings.daily_check(self.gateway, account) if self.risk_settings else None
        if daily and not daily["ok"]:
            decision["execution_status"] = "LIMITE_DIARIO_INDISPONIVEL"
            decision["reasons"].append(daily["detail"])
            self.stop(daily["detail"])
            return
        utc_day = datetime.now(timezone.utc).date().isoformat()
        if self.state.get("risk_day") != utc_day:
            with self._lock:
                self.state.update(risk_day=utc_day, day_start_equity=float(account.get("equity", 0) or 0))
                start_equity = float(self.state.get("day_start_equity") or 0)
        if not self.risk_settings and (start_equity <= 0 or float(account.get("equity", 0)) <= start_equity * 0.99):
            decision["execution_status"] = "LIMITE_DIARIO_ATINGIDO"
            decision["reasons"].append("Equity inválida ou limite diário de perda de 1% atingido; motor parado.")
            self.stop("Limite diário DEMO atingido; verifique equity e posições no MT5.")
            return
        current_tick = tick if tick.get("ok") else {}
        tick_age = time.time() - float(current_tick.get("time", 0) or 0)
        if tick_age < -MAX_FUTURE_TIME_SKEW_SECONDS or tick_age > MAX_TICK_AGE_SECONDS:
            decision["execution_status"] = "COTACAO_DESATUALIZADA"
            decision["reasons"].append("Cotação ausente/desatualizada; sinal descartado.")
            return
        side = decision["side"]
        entry = float(current_tick["ask"] if side == "BUY" else current_tick["bid"])
        stop, target = float(decision["stop"]), float(decision["target"])
        if (side == "BUY" and not stop < entry < target) or (side == "SELL" and not target < entry < stop):
            decision["execution_status"] = "COTACAO_INVALIDOU_SINAL"
            decision["reasons"].append("Preço de execução invalidou a relação entrada/stop/alvo; sinal descartado.")
            return
        target = entry + 1.5 * (entry - stop) if side == "BUY" else entry - 1.5 * (stop - entry)
        policy = self.risk_settings.profile("analyst") if self.risk_settings else None
        risk_cash = (min(self.risk_settings.budget("analyst", account), daily["remaining_cash"])
                     if self.risk_settings else float(account.get("equity", 0)) * 0.001)
        sizing = self.gateway.risk_volume(symbol, side, entry, stop, risk_cash,
                                        policy["max_volume"] if policy else .01,
                                        **({"policy": policy} if policy else {}))
        decision["sizing"] = sizing
        if not sizing.get("ok"):
            decision["execution_status"] = "RISCO_BLOQUEADO"
            decision["reasons"].append(sizing.get("detail", "Dimensionamento falhou."))
            return
        send_order = (self.gateway.send_real_analyst_order if run_mode == "real"
                      else self.gateway.send_demo_analyst_order)
        with self._lock:
            if not self.state.get("running") or self.state.get("mode") != run_mode:
                decision["execution_status"] = "CANCELADA_MOTOR_PARADO"
                decision["reasons"].append("O motor foi parado antes do envio; nenhuma ordem foi solicitada.")
                return
            clock_failure = self._clock_failure(fingerprint)
            if clock_failure:
                decision["execution_status"] = "BLOQUEADO_RELOGIO_UTC"
                decision["reasons"].append(clock_failure)
                self._suspend_for_clock(clock_failure)
                return
            # Keep stop/reconfigure serialized with the final preflight and send.
            # A stop request arriving after this point waits for the current RPC.
            result = send_order(
                symbol, side, sizing["volume"], stop, target, fingerprint, risk_cash,
                float(analysis["technical"]["atr14"]) * 0.08, 1.5,
                **({"risk_policy": policy} if policy else {}))
        reconciled = result.get("ok") is True and result.get("reconciled") is True
        decision["execution_status"] = (
            "CONFIRMADA_MT5" if reconciled
            else "ACEITA_AGUARDANDO_RECONCILIACAO" if result.get("ok") is True
            else "RESULTADO_DESCONHECIDO" if result.get("unknown") or result.get("position_may_remain")
            else "NAO_EXECUTADA")
        decision["execution"] = {key: result.get(key) for key in ("ticket", "order", "deal", "volume", "price", "sl", "tp", "detail")}
        decision["reasons"].append(result.get("detail", "Resultado de envio indisponível."))
        self.database.add_log("INFO" if reconciled else "CRITICAL" if result.get("unknown") or result.get("position_may_remain") or result.get("ok") else "WARN",
                              f"Analista {expected_mode} {symbol} {side}: {result.get('detail', 'sem detalhe')}")
        if result.get("unknown") or result.get("position_may_remain") or (result.get("ok") and not reconciled):
            self.stop(f"Envio/reconciliação {expected_mode} incertos; motor parado e sem repetição automática.",
                      phase="resultado_desconhecido")
