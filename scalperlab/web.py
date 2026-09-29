from __future__ import annotations

import json
import hashlib
import secrets
import uuid
import threading
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, g

from .ai_assistant import AIAssistant
from .config import MAX_REQUEST_BYTES
from .connectors.audit import AuditedTradingPort
from .connectors.manager import ConnectorManager
from .clock_monitor import ClockValidationMonitor, inspect_mt5_clock
from .db import Database
from .risk_settings import RiskSettings, number
from .execution_engine import ExecutionEngine
from .market_analyst import MarketAnalystEngine
from .mt5_gateway import MT5Gateway
from .research import ResearchError, ResearchService
from .replay import (MAX_REPLAY_BARS, MIN_VALIDATION_BARS,
                     ReplayValidationError, run_pullback_validation)
from .strategy_validation import validate_strategy
from .system_clock import SystemClockService
from .sr_quant.service import SrResearchService
from .sr_quant.replay import MIN_M5_BARS, MAX_M5_BARS, run_sr_replay

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VALID_STRATEGY_STATES = {"review", "approved", "rejected"}


def create_app(*, database: Database | None = None, mt5: MT5Gateway | None = None,
               token: str | None = None, terminal_id: str = "default") -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"),
                static_folder=str(PROJECT_ROOT / "static"), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.config["APP_TOKEN"] = token or secrets.token_urlsafe(32)
    app.extensions["scalper_db"] = database or Database()
    risk_settings = RiskSettings(app.extensions["scalper_db"])
    app.extensions["scalper_risk_settings"] = risk_settings
    risk_actions_lock = threading.RLock()
    connector_manager = ConnectorManager()
    app.extensions["scalper_connector_manager"] = connector_manager
    connector = mt5 or connector_manager.get_connector(terminal_id)
    connector_terminal_id = getattr(connector, "terminal_id", terminal_id)
    terminal_config = next((item for item in connector_manager.terminals()
                            if item.terminal_id == connector_terminal_id), None)
    audited_connector = AuditedTradingPort(
        connector, app.extensions["scalper_db"],
        symbol_mappings=terminal_config.symbol_mappings if terminal_config else None)
    audited_connector.risk_settings = risk_settings
    app.extensions["scalper_connector"] = connector
    app.extensions["scalper_order_audit"] = audited_connector
    app.extensions["scalper_mt5"] = audited_connector
    app.extensions["scalper_research"] = ResearchService(app.extensions["scalper_db"])
    app.extensions["scalper_ai"] = AIAssistant()
    app.extensions["scalper_system_clock"] = SystemClockService()
    system_clock = app.extensions["scalper_system_clock"]

    def probe_clock_read_only() -> dict[str, Any]:
        proof = system_clock.snapshot()
        terminal = app.extensions["scalper_mt5"].state()
        if not terminal.get("connected"):
            return {"ok": False, "severity": "transient",
                    "detail": "Terminal MT5 desconectado durante a verificação periódica."}

        account = terminal.get("account") or {}
        fingerprint = (f"{account.get('login')}@{account.get('server')}"
                       if account.get("login") and account.get("server") else None)
        current_terminal_id = str(
            getattr(app.extensions["scalper_connector"], "terminal_id", terminal_id)
        )
        if (not fingerprint or proof.get("mt5_terminal_id") != current_terminal_id
                or proof.get("mt5_account_fingerprint") != fingerprint):
            return {"ok": False, "severity": "hard", "invalidate": True,
                    "detail": "A conta ou o terminal mudou. Verifique novamente o horário UTC."}

        analyst_state = app.extensions["scalper_analyst"].snapshot()
        symbols = analyst_state.get("config", {}).get("symbols") or proof.get("mt5_symbols") or []
        if not symbols:
            return {"ok": False, "severity": "transient",
                    "detail": "Configure símbolos do Market Watch para renovar a validação UTC."}

        diagnostics = system_clock.inspect_read_only()
        if not diagnostics.get("ok"):
            detail = diagnostics.get("detail") or "Não foi possível consultar a fonte UTC."
            hard_fragments = (
                "desvio utc acima do limite", "serviço windows time está parado",
                "não está configurado para iniciar automaticamente",
                "fonte configurada não permite medir",
            )
            severity = "hard" if any(fragment in detail.casefold()
                                      for fragment in hard_fragments) else "transient"
            return {"ok": False, "severity": severity, "detail": detail,
                    "source": diagnostics.get("source"),
                    "ntp_offset_seconds": diagnostics.get("ntp_offset_seconds"),
                    "service_running": diagnostics.get("service_running"),
                    "startup_type": diagnostics.get("startup_type")}

        mt5_check = inspect_mt5_clock(
            app.extensions["scalper_mt5"], list(symbols),
            terminal_id=current_terminal_id, account_fingerprint=fingerprint,
        )
        record_clock_diagnostics(mt5_check)
        return {**diagnostics, **mt5_check,
                "detail": mt5_check.get("detail") or diagnostics.get("detail"),
                "terminal_id": current_terminal_id,
                "account_fingerprint": fingerprint}

    def record_clock_diagnostics(result):
        # activity_log limits each message to 500 characters. Keep one compact
        # record per symbol so no later samples disappear through truncation.
        for item in result.get("mt5_tick_diagnostics", [])[:12]:
            compact = {key: item.get(key) for key in (
                "symbol", "raw_time", "raw_time_msc", "age_seconds",
                "server_utc_offset_seconds", "accepted", "code")}
            compact["source"] = "MQL5"
            compact["reason"] = str(item.get("reason") or "")[:120]
            app.extensions["scalper_db"].add_log(
                "DEBUG", "UTC: " + json.dumps(compact, ensure_ascii=False))

    app.extensions["scalper_clock_monitor"] = ClockValidationMonitor(
        system_clock, probe_clock_read_only,
        on_event=lambda level, detail: app.extensions["scalper_db"].add_log(level, detail),
    )
    app.extensions["scalper_engine"] = ExecutionEngine(
        app.extensions["scalper_db"], app.extensions["scalper_mt5"],
        clock_service=app.extensions["scalper_system_clock"], risk_settings=risk_settings)
    app.extensions["scalper_analyst"] = MarketAnalystEngine(
        app.extensions["scalper_db"], app.extensions["scalper_mt5"],
        clock_service=app.extensions["scalper_system_clock"], risk_settings=risk_settings)
    app.extensions["scalper_sr_research"] = SrResearchService(
        app.extensions["scalper_db"], app.extensions["scalper_mt5"])

    @app.before_request
    def protect_local_api():
        expected_host = app.config.get("APP_HOST")
        if expected_host and request.host != expected_host:
            if request.path.startswith("/api/"):
                return jsonify(error="host_not_allowed"), 403
            if request.path == "/" or request.path.startswith("/static/"):
                return "Host não autorizado", 403
        if request.path.startswith("/api/"):
            origin = request.headers.get("Origin")
            if origin and origin != app.config.get("APP_ORIGIN"):
                return jsonify(error="origin_not_allowed"), 403
            if not secrets.compare_digest(request.headers.get("X-ScalperLab-Token", ""),
                                          app.config["APP_TOKEN"]):
                return jsonify(error="token_required"), 403

    @app.before_request
    def serialize_risk_actions():
        if request.method == "POST" and request.path in {
            "/api/settings/risk", "/api/engine/start", "/api/analyst/start",
            "/api/engine/profile", "/api/analyst/profile", "/api/sr-quant/start",
            "/api/sr-quant/replay", "/api/sr-quant/replay-saved"}:
            risk_actions_lock.acquire()
            g.risk_action_locked = True

    @app.teardown_request
    def release_risk_actions(error=None):
        if getattr(g, "risk_action_locked", False):
            g.risk_action_locked = False
            risk_actions_lock.release()

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'self'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def home():
        token_value = json.dumps(app.config["APP_TOKEN"])
        html = render_template("index.html").replace("__APP_TOKEN__", json.loads(token_value))
        return html

    @app.get("/api/state")
    def state():
        mt5_state = app.extensions["scalper_mt5"].state()
        engine_state = app.extensions["scalper_engine"].snapshot()
        system_clock = app.extensions["scalper_system_clock"]
        clock_snapshot = system_clock.snapshot()
        clock_account = mt5_state.get("account") or {}
        current_terminal_id = str(
            getattr(app.extensions["scalper_connector"], "terminal_id", terminal_id)
        )
        current_fingerprint = (
            f"{clock_account.get('login')}@{clock_account.get('server')}"
            if clock_account.get("login") and clock_account.get("server") else None
        )
        if (clock_snapshot.get("monitor_enabled")
                and (clock_snapshot.get("mt5_terminal_id") != current_terminal_id
                     or clock_snapshot.get("mt5_account_fingerprint") != current_fingerprint)):
            clock_snapshot = system_clock.invalidate(
                "A conta ou o terminal mudou. Verifique novamente o horário UTC antes da execução.")
        return jsonify({"mt5": mt5_state,
                        "risk_settings": risk_settings.snapshot(),
                        "risk_day": risk_settings.daily_snapshot(clock_account),
                        "orders": app.extensions["scalper_mt5"].positions(),
                        "strategies": app.extensions["scalper_db"].list_strategies(),
                        "research": app.extensions["scalper_db"].list_research_items(30),
                        "logs": app.extensions["scalper_db"].list_logs(),
                        "providers": app.extensions["scalper_research"].provider_status(),
                        "engine": engine_state,
                        "analyst": app.extensions["scalper_analyst"].snapshot(),
                        "sr_research": app.extensions["scalper_sr_research"].snapshot(),
                        "sr_data_events": app.extensions["scalper_db"].list_sr_data_events(8),
                        "system_clock": clock_snapshot,
                        "ai": {"available": app.extensions["scalper_ai"].available,
                               "model": app.extensions["scalper_ai"].model},
                        "risk": {"live_trading": "disponivel_com_confirmacao", "demo_armed": mt5_state["demo_armed"],
                                 "real_close_armed": mt5_state.get("real_close_armed", False),
                                 "daily_loss_limit": risk_settings.snapshot()["daily_loss_limit_pct"],
                                 "max_position_size": engine_state["config"].get("max_volume", 0.01)}})

    @app.route("/api/settings/risk", methods=["GET", "POST"])
    def settings_risk():
        if request.method == "GET":
            return jsonify(risk_settings.snapshot())
        if (app.extensions["scalper_analyst"].snapshot()["state"].get("running")
                or app.extensions["scalper_engine"].snapshot()["state"].get("running")):
            return jsonify(ok=False, detail="Pare os dois motores antes de salvar lote e risco."), 409
        data = _json_body() or {}
        try:
            config = risk_settings.save(data.get("engine"), data.get("profile"), data.get("daily_loss_limit_pct"))
            return jsonify(ok=True, detail="Lote e risco salvos. O consumo diário da conta foi preservado.", config=config)
        except (ValueError, TypeError) as exc:
            return jsonify(ok=False, detail=str(exc)), 400

    @app.post("/api/settings/risk/preview")
    def risk_preview():
        data = _json_body() or {}
        gateway = app.extensions["scalper_mt5"]
        try:
            engine = data.get("engine")
            if engine not in {"analyst", "strategy"}:
                raise ValueError("Escolha o motor para a prévia.")
            symbol = _bounded(data.get("symbol"), 64)
            validation = gateway.validate_market_symbols([symbol])
            if not validation.get("available") or not validation.get("valid"):
                raise ValueError("Selecione um ativo válido do Market Watch.")
            side = data.get("side")
            if side not in {"BUY", "SELL"}:
                raise ValueError("Escolha compra ou venda.")
            stop = number(data.get("stop"), "Preço do stop", .00000001, 1e15)
            tick = gateway.current_tick(symbol)
            if not tick.get("ok"):
                raise ValueError(tick.get("detail", "Cotação indisponível."))
            terminal = gateway.state()
            account = terminal.get("account") or {}
            budget = risk_settings.budget(engine, account)
            day = risk_settings.daily_snapshot(account)
            if day.get("available"):
                current_day = risk_settings.daily_check(gateway, account)
                if not current_day["ok"]:
                    raise ValueError(current_day["detail"])
                day = risk_settings.daily_snapshot(account)
                if day.get("blocked"):
                    raise ValueError("Limite diário atingido; novas entradas estão pausadas.")
                budget = min(budget, day["remaining_cash"])
            policy = risk_settings.profile(engine)
            entry = tick["ask"] if side == "BUY" else tick["bid"]
            result = gateway.risk_volume(symbol, side, entry, stop, budget,
                                         policy["max_volume"], policy=policy)
            return jsonify({**result, "entry": entry, "symbol": symbol,
                            "currency": account.get("currency"), "reference_at": tick.get("time"),
                            "daily_reference_available": bool(day.get("available"))}), (200 if result.get("ok") else 400)
        except (ValueError, TypeError, KeyError) as exc:
            return jsonify(ok=False, detail=str(exc)), 400

    @app.post("/api/system/clock/synchronize")
    def synchronize_system_clock():
        analyst_state = app.extensions["scalper_analyst"].snapshot()["state"]
        engine_state = app.extensions["scalper_engine"].snapshot()["state"]
        active_execution = any(
            runtime.get("running") and runtime.get("mode") in {"demo", "real"}
            for runtime in (analyst_state, engine_state)
        )
        if active_execution:
            return jsonify(status="blocked", detail=(
                "Pare a execução DEMO/REAL antes de corrigir o relógio. "
                "A sincronização pode ajustar o relógio do Windows.")), 409

        clock = app.extensions["scalper_system_clock"]
        read_only = (_json_body() or {}).get("read_only") is True
        result = clock.verify_read_only() if read_only else clock.verify_and_synchronize()
        if result.get("status") != "system_synchronized":
            app.extensions["scalper_db"].add_log("WARN", result["detail"])
            return jsonify(result), 409

        terminal = app.extensions["scalper_mt5"].state()
        if not terminal.get("connected"):
            result = clock.set_mt5_result(
                verified=False,
                detail="Conecte o terminal MT5 para validar ticks e offset do servidor.",
                symbols_checked=0, symbols_total=0,
                server_utc_offset_seconds=None,
                symbols=[],
            )
            app.extensions["scalper_db"].add_log("WARN", result["mt5_detail"])
            return jsonify(result), 409
        account = terminal.get("account") or {}
        current_terminal_id = str(
            getattr(app.extensions["scalper_connector"], "terminal_id", terminal_id)
        )
        account_fingerprint = (
            f"{account.get('login')}@{account.get('server')}"
            if account.get("login") and account.get("server") else None
        )

        analyst = app.extensions["scalper_analyst"].snapshot()
        symbols = analyst.get("config", {}).get("symbols", [])
        if not symbols:
            result = clock.set_mt5_result(
                verified=False,
                detail="Configure ao menos um símbolo do Market Watch para validar o horário MT5.",
                symbols_checked=0, symbols_total=0,
                server_utc_offset_seconds=None,
                terminal_id=current_terminal_id,
                account_fingerprint=account_fingerprint,
                symbols=[],
            )
            app.extensions["scalper_db"].add_log("WARN", result["mt5_detail"])
            return jsonify(result), 409

        gateway = app.extensions["scalper_mt5"]
        mt5_check = inspect_mt5_clock(
            gateway, list(symbols), terminal_id=current_terminal_id,
            account_fingerprint=account_fingerprint,
        )
        result = clock.set_mt5_result(
            verified=bool(mt5_check.get("ok")),
            detail=str(mt5_check.get("detail") or "UTC do MT5 não confirmado."),
            symbols_checked=int(mt5_check.get("mt5_symbols_checked", 0)),
            symbols_total=len(symbols),
            server_utc_offset_seconds=mt5_check.get("mt5_server_utc_offset_seconds"),
            terminal_id=current_terminal_id,
            account_fingerprint=account_fingerprint,
            symbols=list(symbols),
            tick_diagnostics=mt5_check.get("mt5_tick_diagnostics", []),
        )
        record_clock_diagnostics(mt5_check)
        app.extensions["scalper_db"].add_log(
            "INFO" if mt5_check.get("ok") else "WARN",
            result["detail"] + " " + str(mt5_check.get("detail", "")))
        return jsonify(result), (200 if mt5_check.get("ok") else 409)

    @app.route("/api/analyst/profile", methods=["GET", "POST"])
    def analyst_profile():
        analyst = app.extensions["scalper_analyst"]
        if request.method == "GET":
            return jsonify(analyst.snapshot())
        data = _json_body()
        if not data:
            return jsonify(error="Envie um objeto JSON válido."), 400
        raw_symbols = data.get("symbols")
        symbols = ([item.strip() for item in raw_symbols
                    if isinstance(item, str) and len(item) <= 64]
                   if isinstance(raw_symbols, list) else _bounded(raw_symbols, 500))
        result = analyst.configure({
            "symbols": symbols,
            "timeframe": _bounded(data.get("timeframe"), 8),
            "decision_basis": _bounded(data.get("decision_basis") or "technical_quantitative", 40),
        })
        if result.get("ok"):
            app.extensions["scalper_system_clock"].invalidate(
                "O perfil do Analista mudou. Verifique novamente o horário UTC antes da execução.")
            app.extensions["scalper_db"].add_log("INFO", "Perfil do analista de mercado atualizado.")
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.get("/api/mt5/market-watch")
    def mt5_market_watch():
        trading_port = app.extensions["scalper_mt5"]
        catalog_method = getattr(trading_port, "market_watch_catalog", None)
        if callable(catalog_method):
            catalog = catalog_method()
        else:
            terminal = trading_port.state()
            symbols = trading_port.market_watch_symbols() if terminal.get("connected") else []
            catalog = {"available": bool(terminal.get("connected")), "source": "MT5 Market Watch",
                       "count": len(symbols), "items": [item.to_dict() for item in symbols],
                       "detail": None if terminal.get("connected") else terminal.get("detail")}
        catalog["terminal_id"] = str(getattr(app.extensions["scalper_connector"], "terminal_id", terminal_id))
        return jsonify(catalog), (200 if catalog.get("available") else 503)

    @app.post("/api/analyst/start")
    def analyst_start():
        if app.extensions["scalper_sr_research"].snapshot()["busy"]:
            return jsonify(ok=False, detail="Pare a pesquisa S/R antes de iniciar o Analista; o conector MT5 é compartilhado."), 409
        data = _json_body() or {}
        mode = _bounded(data.get("mode"), 20)
        result = app.extensions["scalper_analyst"].start(
            mode, _bounded(data.get("confirmation"), 80))
        app.extensions["scalper_db"].add_log("INFO" if result["ok"] else "WARN",
                                             f"Analista de mercado: {result['detail']}")
        return jsonify(result), (200 if result.get("ok") else 409)

    @app.post("/api/analyst/stop")
    def analyst_stop():
        result = app.extensions["scalper_analyst"].stop()
        app.extensions["scalper_db"].add_log("INFO", f"Analista de mercado: {result['detail']}")
        return jsonify(result)

    @app.post("/api/sr-quant/start")
    def sr_quant_start():
        if (app.extensions["scalper_analyst"].snapshot()["state"].get("running")
                or app.extensions["scalper_engine"].snapshot()["state"].get("running")):
            return jsonify(ok=False, detail="Pare os motores antes de iniciar a pesquisa S/R; o conector MT5 é compartilhado."), 409
        data = _json_body() or {}
        result = app.extensions["scalper_sr_research"].start(data.get("symbols"))
        app.extensions["scalper_db"].add_log(
            "INFO" if result["ok"] else "WARN", f"Pesquisa S/R: {result['detail']}")
        return jsonify(result), (200 if result["ok"] else 409)

    @app.post("/api/sr-quant/stop")
    def sr_quant_stop():
        result = app.extensions["scalper_sr_research"].stop()
        app.extensions["scalper_db"].add_log("INFO", f"Pesquisa S/R: {result['detail']}")
        return jsonify(result)

    @app.get("/api/sr-quant/evaluations")
    def sr_quant_evaluations():
        return jsonify(items=app.extensions["scalper_db"].list_sr_evaluations(100))

    @app.get("/api/sr-quant/data-events")
    def sr_quant_data_events():
        return jsonify(items=app.extensions["scalper_db"].list_sr_data_events(100))

    @app.get("/api/sr-quant/replays")
    def sr_quant_replays():
        return jsonify(items=app.extensions["scalper_db"].list_sr_replay_runs(20))

    @app.post("/api/sr-quant/replay-saved")
    def sr_quant_replay_saved():
        if (app.extensions["scalper_sr_research"].snapshot()["busy"]
                or app.extensions["scalper_analyst"].snapshot()["state"].get("running")
                or app.extensions["scalper_engine"].snapshot()["state"].get("running")):
            return jsonify(error="Pare os motores antes de reproduzir o histórico salvo."), 409
        saved = app.extensions["scalper_db"].list_sr_replay_runs(1)
        if not saved:
            return jsonify(error="Nenhum replay S/R salvo nesta instalação."), 404
        record = app.extensions["scalper_db"].get_sr_replay_run(saved[0]["run_id"])
        if record is None:
            return jsonify(error="Histórico S/R salvo indisponível."), 404
        parameters = record["parameters"]
        dataset = record["dataset"]
        try:
            result = run_sr_replay(
                symbol=record["symbol"], frames=dataset["frames"],
                contract=dataset["contract"],
                slippage_points=parameters["slippage_points_per_side"],
                commission_per_lot_round_turn=parameters["commission_per_lot_round_turn"],
                swap_long_per_lot_per_utc_rollover=parameters["swap_long_per_lot_per_utc_rollover"],
                swap_short_per_lot_per_utc_rollover=parameters["swap_short_per_lot_per_utc_rollover"],
                costs_confirmed=parameters["costs_confirmed"])
        except (ReplayValidationError, KeyError, ValueError, TypeError) as exc:
            return jsonify(error=f"Histórico salvo incompatível: {exc}"), 409
        if result["data_sha256"] != record["data_sha256"]:
            return jsonify(error="Hash do replay salvo divergiu; resultado descartado."), 409
        return jsonify(result={**result, "run_id": record["run_id"], "offline": True},
                       detail="Replay S/R reproduzido do histórico local com hash conferido; sem consultar o MT5."), 200

    @app.post("/api/sr-quant/replay")
    def sr_quant_replay():
        if (app.extensions["scalper_sr_research"].snapshot()["busy"]
                or app.extensions["scalper_analyst"].snapshot()["state"].get("running")
                or app.extensions["scalper_engine"].snapshot()["state"].get("running")):
            return jsonify(error="Pare os motores e a pesquisa S/R antes do replay; o conector MT5 é compartilhado."), 409
        data = _json_body() or {}
        if data.get("costs_confirmed") is not True:
            return jsonify(error="Confirme os custos informados para o replay."), 400
        symbol = _bounded(data.get("symbol"), 32)
        try:
            count = int(data.get("bars", 0))
        except (TypeError, ValueError):
            return jsonify(error="Quantidade de candles inválida."), 400
        if count < MIN_M5_BARS or count > MAX_M5_BARS:
            return jsonify(error=f"Use de {MIN_M5_BARS} a {MAX_M5_BARS} candles M5."), 400
        port = app.extensions["scalper_mt5"]
        catalog = port.market_watch_catalog()
        if not catalog.get("available"):
            return jsonify(error=catalog.get("detail") or "Market Watch indisponível."), 503
        if symbol not in {item["broker_symbol"] for item in catalog.get("items", [])
                          if item.get("trade_enabled")}:
            return jsonify(error="Selecione um ativo negociável com o nome exato do Market Watch."), 400
        terminal = port.state()
        account = terminal.get("account") or {}
        if not terminal.get("connected") or not account.get("login") or not account.get("server"):
            return jsonify(error="Conta MT5 indisponível."), 503
        frames = {}
        normalization = {}
        contract = None
        counts = {"M5": count, "M15": min(2000, (count + 2) // 3 + 260),
                  "H1": min(1000, (count + 11) // 12 + 260)}
        for frame in ("H1", "M15", "M5"):
            response = port.historical_market_data(symbol, counts[frame], frame)
            if not response.get("ok") or response.get("symbol") != symbol:
                return jsonify(error=response.get("detail") or f"Histórico {frame} indisponível."), 409
            evidence = response.get("time_normalization") or {}
            if evidence.get("basis") != "UTC" or evidence.get("historical_timezone_verified") is not True:
                return jsonify(error=f"Base UTC histórica {frame} não confirmada; replay bloqueado."), 409
            frames[frame] = response.get("bars") or []
            normalization[frame] = evidence
            if contract is None:
                contract = response.get("contract") or {}
        try:
            result = run_sr_replay(
                symbol=symbol, frames=frames, contract=contract or {},
                slippage_points=data.get("slippage_points", 0),
                commission_per_lot_round_turn=data.get("commission_per_lot_round_turn", 0),
                swap_long_per_lot_per_utc_rollover=data.get("swap_long_per_lot_per_utc_rollover", 0),
                swap_short_per_lot_per_utc_rollover=data.get("swap_short_per_lot_per_utc_rollover", 0),
                costs_confirmed=True)
        except (ReplayValidationError, ValueError, TypeError) as exc:
            return jsonify(error=str(exc)), 409
        account_identity = hashlib.sha256(
            f'{connector_terminal_id}:{account["login"]}@{account["server"]}'.encode()).hexdigest()
        run_id = str(uuid.uuid4())
        app.extensions["scalper_db"].save_sr_replay_run(
            run_id=run_id, terminal_id=connector_terminal_id, account_sha256=account_identity,
            symbol=symbol, result=result,
            dataset={"frames": frames, "contract": contract,
                     "time_normalization": normalization})
        return jsonify(result={**result, "run_id": run_id},
                       detail="Replay S/R concluído e salvo. Triagem OHLC; nenhum motor foi armado."), 200

    @app.get("/api/analyst/replays")
    def analyst_replays():
        return jsonify(items=app.extensions["scalper_db"].list_replay_runs(20))

    @app.get("/api/analyst/replays/<run_id>")
    def analyst_replay_detail(run_id: str):
        replay = app.extensions["scalper_db"].get_replay_run(_bounded(run_id, 80))
        return (jsonify(replay=replay), 200) if replay else (jsonify(error="Replay não encontrado."), 404)

    @app.post("/api/analyst/replay-saved")
    def replay_saved():
        records = app.extensions["scalper_db"].list_replay_runs(1)
        if not records:
            return jsonify(error="Nenhum histórico validado foi salvo. Faça primeiro uma coleta com o MT5 conectado."), 404
        saved = app.extensions["scalper_db"].get_replay_run(records[0]["run_id"])
        dataset = saved["dataset"]
        parameters = saved["parameters"]
        expected = hashlib.sha256(json.dumps(
            {"bars": dataset["bars"], "contract": dataset["contract"], "parameters": parameters},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
        ).encode("utf-8")).hexdigest()
        if expected != saved["data_sha256"]:
            return jsonify(error="Integridade do histórico salvo não confirmada; replay cancelado."), 409
        try:
            result = run_pullback_validation(
                symbol=saved["symbol"], timeframe=saved["timeframe"],
                bars=dataset["bars"], contract=dataset["contract"],
                slippage_points=parameters["slippage_points_per_side"],
                commission_per_lot_round_turn=parameters["commission_per_lot_round_turn"],
                swap_long_per_lot_per_utc_rollover=parameters["swap_long_per_lot_per_utc_rollover"],
                swap_short_per_lot_per_utc_rollover=parameters["swap_short_per_lot_per_utc_rollover"],
                costs_confirmed=parameters["costs_confirmed"])
        except (ReplayValidationError, KeyError, ValueError) as exc:
            return jsonify(error=f"Histórico incompatível: {exc}"), 409
        result.update(run_id=saved["run_id"], offline=True)
        return jsonify(result=result, detail="Replay offline do último histórico salvo, com hash conferido e custos originais. Não consulta o MT5 nem envia ordens.")

    @app.post("/api/analyst/replay")
    def analyst_replay():
        data = _json_body()
        if not data:
            return jsonify(error="Envie os parâmetros do replay."), 400
        analyst_state = app.extensions["scalper_analyst"].snapshot().get("state", {})
        engine_state = app.extensions["scalper_engine"].snapshot().get("state", {})
        if (analyst_state.get("running") or engine_state.get("running")
                or app.extensions["scalper_sr_research"].snapshot()["busy"]):
            return jsonify(error="Pare os motores antes de iniciar o replay; isso evita disputar o conector MT5 com a execução DEMO/REAL."), 409
        if data.get("costs_confirmed") is not True:
            return jsonify(error="Confirme que spread, slippage, comissão e swap foram informados com base na corretora."), 400
        symbol = _bounded(data.get("symbol"), 32)
        timeframe = _bounded(data.get("timeframe"), 8).upper()
        try:
            count = int(data.get("bars", 0))
        except (TypeError, ValueError):
            return jsonify(error="Quantidade de candles inválida."), 400
        if count < MIN_VALIDATION_BARS or count > MAX_REPLAY_BARS:
            return jsonify(error=f"Informe de {MIN_VALIDATION_BARS} a {MAX_REPLAY_BARS} candles fechados para separar desenvolvimento e holdout."), 400
        connector = app.extensions["scalper_mt5"]
        catalog = connector.market_watch_catalog()
        if not catalog.get("available"):
            return jsonify(error=catalog.get("detail") or "Catálogo do Market Watch indisponível."), 503
        selected = next((item for item in catalog.get("items", [])
                         if item.get("broker_symbol") == symbol), None)
        if not selected:
            return jsonify(error="Selecione um ativo exato que esteja visível no Market Watch do MT5."), 400
        if not selected.get("trade_enabled"):
            return jsonify(error="O ativo está somente para leitura no MT5 e não pode ser simulado como ordem."), 409
        market_data = connector.historical_market_data(symbol, count, timeframe)
        if not market_data.get("ok"):
            return jsonify(error=market_data.get("detail") or "Histórico MT5 indisponível."), 503
        if int(market_data.get("contract", {}).get("trade_mode", -1)) != 4:
            return jsonify(error="O ativo não aceita BUY e SELL em ambos os sentidos; replay cancelado."), 409
        try:
            result = run_pullback_validation(
                symbol=symbol, timeframe=timeframe, bars=market_data.get("bars", []),
                contract=market_data.get("contract", {}),
                slippage_points=data.get("slippage_points", 1.0),
                commission_per_lot_round_turn=data.get("commission_per_lot_round_turn", 0.0),
                swap_long_per_lot_per_utc_rollover=data.get("swap_long_per_lot_per_utc_rollover", 0.0),
                swap_short_per_lot_per_utc_rollover=data.get("swap_short_per_lot_per_utc_rollover", 0.0),
                costs_confirmed=True,
            )
        except ReplayValidationError as exc:
            return jsonify(error=str(exc)), 400
        account = (connector.state().get("account") or {})
        fingerprint = f"{account.get('login')}@{account.get('server')}"
        fingerprint_hash = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest() if "@" in fingerprint else ""
        run_id = str(uuid.uuid4())
        result["run_id"] = run_id
        result["account_mode"] = account.get("mode")
        result["terminal_id"] = str(getattr(app.extensions["scalper_connector"], "terminal_id", terminal_id))
        result["time_normalization"] = market_data.get("time_normalization", {})
        dataset = {"source": "MetaTrader 5 Python API · histórico OHLC do broker",
                   "bars": market_data.get("bars", []),
                   "contract": market_data.get("contract", {}),
                   "time_normalization": market_data.get("time_normalization", {}),
                   "split": result["parameters"]}
        app.extensions["scalper_db"].save_replay_run(
            run_id=run_id, terminal_id=result["terminal_id"],
            account_fingerprint_sha256=fingerprint_hash,
            symbol=symbol, timeframe=timeframe, data_sha256=result["data_sha256"],
            parameters=result["parameters"], result=result, dataset=dataset,
        )
        metric = result["metrics"]
        app.extensions["scalper_db"].add_log(
            "INFO", f"Validação OHLC {symbol} {timeframe}: holdout pullback={metric['closed_trades']} trade(s), "
            f"baseline={result['comparison']['baseline_closed_trades']}; nenhum envio ao MT5 foi feito.")
        return jsonify(result=result,
                       detail="Comparação cronológica concluída com OHLC do broker. Nenhuma ordem foi enviada."), 200

    @app.route("/api/engine/profile", methods=["GET", "POST"])
    def engine_profile():
        engine = app.extensions["scalper_engine"]
        if request.method == "GET":
            return jsonify(engine.snapshot())
        data = _json_body()
        if not data:
            return jsonify(error="Envie um objeto JSON válido."), 400
        result = engine.configure(data, app.extensions["scalper_db"].list_strategies())
        if result.get("ok"):
            app.extensions["scalper_db"].add_log("INFO", "Perfil declarativo do motor atualizado.")
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.post("/api/engine/start")
    def engine_start():
        if app.extensions["scalper_sr_research"].snapshot()["busy"]:
            return jsonify(ok=False, detail="Pare a pesquisa S/R antes de iniciar o motor; o conector MT5 é compartilhado."), 409
        data = _json_body() or {}
        mode = _bounded(data.get("mode"), 20)
        result = app.extensions["scalper_engine"].start(
            mode, _bounded(data.get("confirmation"), 80),
            app.extensions["scalper_db"].list_strategies())
        app.extensions["scalper_db"].add_log("INFO" if result.get("ok") else "WARN",
                                             f"Motor de estratégias: {result['detail']}")
        return jsonify(result), (200 if result.get("ok") else 409)

    @app.post("/api/engine/stop")
    def engine_stop():
        result = app.extensions["scalper_engine"].stop()
        app.extensions["scalper_db"].add_log("INFO", f"Motor de estratégias: {result['detail']}")
        return jsonify(result)

    @app.get("/api/strategies")
    def strategies_list():
        return jsonify(items=app.extensions["scalper_db"].list_strategies())

    @app.get("/api/strategies/<int:strategy_id>/source")
    def strategies_source(strategy_id: int):
        item = app.extensions["scalper_db"].get_strategy_source(strategy_id)
        if not item:
            return jsonify(error="Estratégia não encontrada."), 404
        if not item.get("file_name") or not item.get("source_code"):
            return jsonify(error="Esta estratégia não possui arquivo importado."), 404
        return jsonify(filename=item["file_name"], source_code=item["source_code"])

    @app.post("/api/strategies")
    def strategies_create():
        data = _json_body()
        if not data:
            return jsonify(error="Envie um objeto JSON válido."), 400
        name = _bounded(data.get("name"), 120)
        description = _bounded(data.get("description"), 8_000)
        source_type = "description"
        file_name = None
        source_code = ""
        validation: dict[str, Any] = {"ok": True, "kind": "description",
                                      "summary": "Descrição guardada para revisão humana.", "warnings": []}
        if data.get("filename") or data.get("source_code"):
            file_name = _bounded(data.get("filename"), 240)
            source_code = _bounded(data.get("source_code"), 1_000_000)
            if not file_name or not source_code:
                return jsonify(error="Envie o nome e o conteúdo completo do arquivo .mq5, .py ou .txt."), 400
            validation = validate_strategy(file_name, source_code)
            if validation["kind"] == "unsupported":
                return jsonify(error=validation["summary"]), 400
            source_type = validation["kind"]
            adaptation = validation.get("adaptation", {})
            name = name or adaptation.get("suggested_name", "")
            description = description or adaptation.get("suggested_description", "")
        if not name or not description:
            return jsonify(error="Informe nome e descrição/regras ou importe um arquivo .mq5, .py ou .txt."), 400
        item = app.extensions["scalper_db"].create_strategy(
            name=name, description=description, source_type=source_type, file_name=file_name,
            source_code=source_code, validation=validation, status="draft")
        app.extensions["scalper_db"].add_log("INFO", f"Estratégia criada: {name}")
        return jsonify(item=item), 201

    @app.put("/api/strategies/<int:strategy_id>/review")
    def strategies_review(strategy_id: int):
        data = _json_body()
        status = data.get("status") if data else None
        item = app.extensions["scalper_db"].get_strategy(strategy_id)
        if not item:
            return jsonify(error="Estratégia não encontrada."), 404
        if status not in VALID_STRATEGY_STATES:
            return jsonify(error="Estado inválido."), 400
        if status == "approved" and not item["validation"].get("ok"):
            return jsonify(error="Estratégia com validação inválida não pode ser aprovada."), 409
        updated = app.extensions["scalper_db"].update_strategy_status(strategy_id, status)
        app.extensions["scalper_db"].add_log("INFO", f"Estratégia {strategy_id}: estado {status}")
        return jsonify(item=updated, note="Aprovação não inicia automação nem libera conta real.")

    @app.post("/api/strategies/validate")
    def strategies_validate():
        data = _json_body()
        if not data:
            return jsonify(error="Envie um objeto JSON válido."), 400
        return jsonify(result=validate_strategy(_bounded(data.get("filename"), 240),
                                               _bounded(data.get("source_code"), 1_000_000)))

    @app.post("/api/research/search")
    def research_search():
        data = _json_body()
        try:
            result = app.extensions["scalper_research"].search(_bounded(data.get("query") if data else "", 240))
        except ResearchError as exc:
            return jsonify(error=str(exc)), 400
        app.extensions["scalper_db"].add_log("INFO", f"Pesquisa concluída; {len(result['items'])} resultado(s).")
        return jsonify(result)

    @app.post("/api/research/import-url")
    def research_import_url():
        data = _json_body()
        try:
            result = app.extensions["scalper_research"].import_url(_bounded(data.get("url") if data else "", 2000))
        except ResearchError as exc:
            return jsonify(error=str(exc)), 400
        app.extensions["scalper_db"].add_log("INFO", f"Fonte importada; {result['saved']} novo(s) item(ns).")
        return jsonify(result)

    @app.route("/api/research/feeds", methods=["GET", "POST"])
    def research_feeds():
        db = app.extensions["scalper_db"]
        if request.method == "GET":
            return jsonify(items=db.list_feeds())
        data = _json_body()
        try:
            result = app.extensions["scalper_research"].register_feed(
                _bounded(data.get("url") if data else "", 2000),
                _bounded(data.get("label") if data else "", 100) or "Feed")
        except ResearchError as exc:
            return jsonify(error=str(exc)), 400
        return jsonify(item=result["feed"], imported=result["saved"]), 201

    @app.post("/api/research/summarize")
    def research_summarize():
        data = _json_body()
        ids = data.get("ids", []) if data else []
        if not isinstance(ids, list) or not ids or len(ids) > 12 or any(not isinstance(value, int) for value in ids):
            return jsonify(error="Selecione de 1 a 12 fontes da pesquisa."), 400
        all_items = app.extensions["scalper_db"].list_research_items(200)
        selected = [item for item in all_items if item["id"] in set(ids)]
        if len(selected) != len(set(ids)):
            return jsonify(error="Uma ou mais fontes não foram encontradas."), 404
        try:
            summary = app.extensions["scalper_ai"].summarize(selected)
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 503
        app.extensions["scalper_db"].add_log("INFO", f"Resumo de pesquisa gerado para {len(selected)} fonte(s).")
        return jsonify(summary=summary, disclaimer="Síntese de pesquisa; não é sinal nem recomendação operacional.")

    @app.get("/api/orders")
    def orders():
        return jsonify(app.extensions["scalper_mt5"].positions())

    @app.get("/api/trading/audit")
    def trading_audit():
        return jsonify(items=app.extensions["scalper_order_audit"].list())

    @app.post("/api/trading/audit/reconcile")
    def reconcile_trading_audit():
        data = _json_body() or {}
        correlation_id = _bounded(data.get("correlation_id"), 80) or None
        results = app.extensions["scalper_order_audit"].reconcile_pending(
            correlation_id=correlation_id, limit=50)
        return jsonify(items=results)

    @app.post("/api/trading/arm-demo")
    def arm_demo():
        data = _json_body()
        result = app.extensions["scalper_mt5"].arm_demo(_bounded(data.get("confirmation") if data else "", 80))
        app.extensions["scalper_db"].add_log("WARN" if not result["ok"] else "INFO", result["detail"])
        return jsonify(result), (200 if result["ok"] else 409)

    @app.post("/api/trading/arm-real-close")
    def arm_real_close():
        data = _json_body()
        result = app.extensions["scalper_mt5"].arm_real_closing(
            _bounded(data.get("confirmation") if data else "", 100))
        app.extensions["scalper_db"].add_log("CRITICAL" if result["ok"] else "WARN", result["detail"])
        return jsonify(result), (200 if result["ok"] else 409)

    @app.post("/api/trading/test-order")
    def demo_test_order():
        data = _json_body()
        result = app.extensions["scalper_mt5"].place_demo_smoke_order(
            _bounded(data.get("confirmation") if data else "", 80))
        level = "INFO" if result.get("ok") else "CRITICAL" if result.get("position_may_remain") else "WARN"
        app.extensions["scalper_db"].add_log(level, result["detail"])
        return jsonify(result), (200 if result.get("ok") else 409)

    @app.post("/api/orders/<int:ticket>/close")
    def close_position(ticket: int):
        data = _json_body()
        confirmation = _bounded(data.get("confirmation") if data else "", 80)
        result = (app.extensions["scalper_mt5"].close_real_position(ticket, confirmation)
                  if confirmation == "FECHAR POSIÇÃO REAL" else
                  app.extensions["scalper_mt5"].close_demo_position(ticket, confirmation))
        app.extensions["scalper_db"].add_log("INFO" if result["ok"] else "WARN",
                                             f"Fechamento {ticket}: {result['detail']}")
        return jsonify(result), (200 if result["ok"] else 409)

    @app.post("/api/trading/emergency-stop")
    def emergency_stop():
        app.extensions["scalper_engine"].stop(
            "Parado pela parada de emergência; confira as posições após a ação.")
        app.extensions["scalper_analyst"].stop()
        app.extensions["scalper_sr_research"].stop()
        data = _json_body()
        confirmation = _bounded(data.get("confirmation") if data else "", 100)
        gateway = app.extensions["scalper_mt5"]
        result = (gateway.emergency_stop_real(confirmation)
                  if confirmation == "FECHAR TODAS AS POSIÇÕES REAL"
                  else gateway.emergency_stop_demo(confirmation))
        result["engine_stopped"] = not app.extensions["scalper_engine"].snapshot()["state"]["running"]
        if not result["engine_stopped"]:
            result["ok"] = False
            result["status"] = "partial"
            result["detail"] = "O fechamento foi processado, mas o motor não confirmou a parada. Verifique o estado antes de retomar operações."
            gateway.update_emergency_action(status="partial", detail=result["detail"])
        app.extensions["scalper_db"].add_log("CRITICAL" if result["ok"] else "WARN", result["detail"])
        return jsonify(result), (200 if result["ok"] else 409)

    @app.get("/api/logs")
    def logs():
        return jsonify(items=app.extensions["scalper_db"].list_logs())

    return app


def _json_body() -> dict[str, Any] | None:
    if not request.is_json:
        return None
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def _bounded(value: Any, max_length: int) -> str:
    return value[:max_length].strip() if isinstance(value, str) else ""
