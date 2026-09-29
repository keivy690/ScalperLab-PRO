"""Shared persisted risk policies; MT5 calculations remain behind TradingPort."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Any


def number(value, name: str, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name}: informe um número válido.")
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ValueError(f"{name}: informe um número válido.") from None
    if not math.isfinite(result) or not low <= result <= high:
        raise ValueError(f"{name}: permitido de {low:g} a {high:g}.")
    return result


def validate_policy(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Perfil de risco inválido.")
    mode = raw.get("sizing_mode", "risk_pct")
    if mode not in {"risk_pct", "risk_cash", "fixed_lot"}:
        raise ValueError("Modo de dimensionamento inválido.")
    result = {"sizing_mode": mode,
              "risk_per_trade_pct": number(raw.get("risk_per_trade_pct", .1), "Risco (%)", .001, 100),
              "risk_cash": number(raw.get("risk_cash", 10), "Risco monetário", .01, 1e12),
              "fixed_volume": number(raw.get("fixed_volume", .01), "Lote fixo", .00000001, 1e8),
              "max_volume": number(raw.get("max_volume", .01), "Lote máximo", .00000001, 1e8),
              "margin_reserve_pct": number(raw.get("margin_reserve_pct", 20), "Reserva de margem (%)", 0, 99.99)}
    if mode == "fixed_lot" and result["fixed_volume"] > result["max_volume"]:
        raise ValueError("Lote fixo não pode ultrapassar o lote máximo.")
    return result


class RiskSettings:
    def __init__(self, database):
        self.database = database
        self.lock = threading.RLock()
        with database.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS risk_settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), config_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS risk_days (
                    account_key TEXT NOT NULL, risk_day TEXT NOT NULL,
                    state_json TEXT NOT NULL, PRIMARY KEY(account_key,risk_day));
            """)
            row = db.execute("SELECT config_json FROM risk_settings WHERE id=1").fetchone()
        if row is None:
            legacy = database.get_engine_runtime().get("config", {})
            profiles = {"analyst": validate_policy({}), "strategy": validate_policy({
                "risk_per_trade_pct": legacy.get("risk_per_trade_pct", .25),
                "max_volume": legacy.get("max_volume", .01)})}
            initial = {"version": 1, "profiles": profiles,
                       "daily_loss_limit_pct": min(1., float(legacy.get("daily_loss_limit_pct", 1.)))}
            with database.connect() as db:
                db.execute("INSERT OR IGNORE INTO risk_settings VALUES(1,?)", (json.dumps(initial),))

    def snapshot(self) -> dict:
        with self.database.connect() as db:
            row = db.execute("SELECT config_json FROM risk_settings WHERE id=1").fetchone()
        return json.loads(row[0])

    def profile(self, engine: str) -> dict:
        config = self.snapshot()
        return {**validate_policy(config["profiles"][engine]), "version": config["version"]}

    def save(self, engine: str, raw: dict, daily) -> dict:
        if engine not in {"analyst", "strategy"}:
            raise ValueError("Escolha Analista ou Estratégias.")
        profile = validate_policy(raw)
        daily = number(daily, "Perda diária (%)", .001, 100)
        with self.lock:
            config = self.snapshot()
            config["profiles"][engine] = profile
            config.update(daily_loss_limit_pct=daily, version=config["version"] + 1)
            with self.database.connect() as db:
                db.execute("UPDATE risk_settings SET config_json=? WHERE id=1", (json.dumps(config),))
            self.database.add_log("INFO", f"Lote e risco: perfil {engine} salvo, versão {config['version']}.")
            return config

    def budget(self, engine: str, account: dict) -> float:
        p = self.profile(engine)
        equity = number(account.get("equity"), "Patrimônio", .00000001, 1e15)
        return p["risk_cash"] if p["sizing_mode"] == "risk_cash" else equity * p["risk_per_trade_pct"] / 100

    @staticmethod
    def account_key(account: dict) -> str:
        if not account.get("login") or not account.get("server") or not account.get("mode"):
            raise ValueError("Identidade da conta indisponível para o limite diário.")
        return hashlib.sha256(f"{account['server']}|{account['login']}|{account['mode']}".encode()).hexdigest()

    def daily_snapshot(self, account: dict) -> dict:
        try:
            key = self.account_key(account)
        except ValueError:
            return {"available": False, "detail": "Conecte uma conta para consultar o limite diário."}
        day = datetime.now(timezone.utc).date().isoformat()
        with self.database.connect() as db:
            row = db.execute("SELECT state_json FROM risk_days WHERE account_key=? AND risk_day=?", (key, day)).fetchone()
        if not row:
            return {"available": False, "detail": "Referência será registrada ao iniciar execução; período contado desde essa leitura."}
        result = json.loads(row[0])
        result.pop("external_initial", None)
        return {"available": True, **result}

    def daily_check(self, gateway, account: dict) -> dict:
        """Reference starts at first verified observation, never pretends to be midnight."""
        with self.lock:
            now = datetime.now(timezone.utc)
            try:
                key = self.account_key(account)
                equity = number(account.get("equity"), "Patrimônio", .00000001, 1e15)
                history = gateway.history_deals((now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=7)).isoformat(),
                                                (now + timedelta(days=1)).isoformat())
                if not history.get("available"):
                    raise ValueError("Histórico de saldo indisponível; limite diário não confirmado.")
                # Wide query accommodates the existing broker timestamp encoding.
                # Differences are by deal identity, never guessed timestamp offsets.
                external = {str(d["ticket"]): number(d.get("profit", 0), "Movimento de saldo", -1e15, 1e15)
                            for d in history.get("items", []) if d.get("type") in {2, 3}}
                with self.database.connect() as db:
                    row = db.execute("SELECT state_json FROM risk_days WHERE account_key=? AND risk_day=?",
                                     (key, now.date().isoformat())).fetchone()
                    state = json.loads(row[0]) if row else {
                        "reference_at": now.isoformat(), "reference_equity": equity,
                        "external_initial": external, "blocked": False}
                    initial = state["external_initial"]
                    if not set(initial).issubset(external):
                        raise ValueError("Histórico de saldo incompleto; referência diária preservada, novas entradas aguardam reconciliação.")
                    if any(external[k] != v for k, v in initial.items()):
                        raise ValueError("Movimento histórico de saldo foi revisado; confira a conta antes de operar.")
                    flows = sum(v for k, v in external.items() if k not in initial)
                    loss = max(0., state["reference_equity"] + flows - equity)
                    cap = state["reference_equity"] * self.snapshot()["daily_loss_limit_pct"] / 100
                    state.update(loss_cash=loss, limit_cash=cap, external_flows=flows,
                                 remaining_cash=max(0., cap - loss), checked_at=now.isoformat(),
                                 blocked=state["blocked"] or loss >= cap)
                    db.execute("INSERT OR REPLACE INTO risk_days VALUES(?,?,?)",
                               (key, now.date().isoformat(), json.dumps(state)))
                return {"ok": not state["blocked"], "detail": "Limite diário atingido; novas entradas pausadas até o próximo dia UTC." if state["blocked"] else "Limite diário disponível.",
                        "remaining_cash": state["remaining_cash"]}
            except (ValueError, TypeError, KeyError, AttributeError) as exc:
                return {"ok": False, "detail": str(exc)}
