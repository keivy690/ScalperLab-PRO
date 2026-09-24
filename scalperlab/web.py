from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from .ai_assistant import AIAssistant
from .config import MAX_REQUEST_BYTES
from .connectors.manager import ConnectorManager
from .db import Database
from .execution_engine import ExecutionEngine
from .market_analyst import MarketAnalystEngine
from .mt5_gateway import MT5Gateway
from .research import ResearchError, ResearchService
from .strategy_validation import validate_strategy

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VALID_STRATEGY_STATES = {"review", "approved", "rejected"}


def create_app(*, database: Database | None = None, mt5: MT5Gateway | None = None,
               token: str | None = None, terminal_id: str = "default") -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_ROOT / "templates"),
                static_folder=str(PROJECT_ROOT / "static"), static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.config["APP_TOKEN"] = token or secrets.token_urlsafe(32)
    app.extensions["scalper_db"] = database or Database()
    connector_manager = ConnectorManager()
    app.extensions["scalper_connector_manager"] = connector_manager
    app.extensions["scalper_mt5"] = mt5 or connector_manager.get_connector(terminal_id)
    app.extensions["scalper_research"] = ResearchService(app.extensions["scalper_db"])
    app.extensions["scalper_ai"] = AIAssistant()
    app.extensions["scalper_engine"] = ExecutionEngine(
        app.extensions["scalper_db"], app.extensions["scalper_mt5"])
    app.extensions["scalper_analyst"] = MarketAnalystEngine(
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
        return jsonify({"mt5": mt5_state,
                        "orders": app.extensions["scalper_mt5"].positions(),
                        "strategies": app.extensions["scalper_db"].list_strategies(),
                        "research": app.extensions["scalper_db"].list_research_items(30),
                        "logs": app.extensions["scalper_db"].list_logs(),
                        "providers": app.extensions["scalper_research"].provider_status(),
                        "engine": engine_state,
                        "analyst": app.extensions["scalper_analyst"].snapshot(),
                        "ai": {"available": app.extensions["scalper_ai"].available,
                               "model": app.extensions["scalper_ai"].model},
                        "risk": {"live_trading": "disponivel_com_confirmacao", "demo_armed": mt5_state["demo_armed"],
                                 "real_close_armed": mt5_state.get("real_close_armed", False),
                                 "daily_loss_limit": engine_state["config"].get("daily_loss_limit_pct"),
                                 "max_position_size": engine_state["config"].get("max_volume", 0.01)}})

    @app.route("/api/analyst/profile", methods=["GET", "POST"])
    def analyst_profile():
        analyst = app.extensions["scalper_analyst"]
        if request.method == "GET":
            return jsonify(analyst.snapshot())
        data = _json_body()
        if not data:
            return jsonify(error="Envie um objeto JSON válido."), 400
        result = analyst.configure({
            "symbols": _bounded(data.get("symbols"), 500),
            "timeframe": _bounded(data.get("timeframe"), 8),
        })
        if result.get("ok"):
            app.extensions["scalper_db"].add_log("INFO", "Perfil do analista de mercado atualizado.")
        return jsonify(result), (200 if result.get("ok") else 400)

    @app.post("/api/analyst/start")
    def analyst_start():
        data = _json_body() or {}
        result = app.extensions["scalper_analyst"].start(
            _bounded(data.get("mode"), 20), _bounded(data.get("confirmation"), 80))
        app.extensions["scalper_db"].add_log("INFO" if result["ok"] else "WARN",
                                             f"Analista de mercado: {result['detail']}")
        return jsonify(result), (200 if result.get("ok") else 409)

    @app.post("/api/analyst/stop")
    def analyst_stop():
        result = app.extensions["scalper_analyst"].stop()
        app.extensions["scalper_db"].add_log("INFO", f"Analista de mercado: {result['detail']}")
        return jsonify(result)

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
        data = _json_body() or {}
        result = app.extensions["scalper_engine"].start(
            _bounded(data.get("mode"), 20), _bounded(data.get("confirmation"), 80),
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
