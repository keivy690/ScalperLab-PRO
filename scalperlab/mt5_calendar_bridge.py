from __future__ import annotations

import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BRIDGE_FILE = "ScalperLab_calendar_v1.json"
MAX_BRIDGE_BYTES = 4_000_000
MAX_AGE_SECONDS = 300
MAX_EVENTS = 2_000
CLOCK_FILE = "ScalperLab_clock_v2.json"
CLOCK_MAX_AGE_SECONDS = 45


def read_clock_export(commondata_path: str | Path | None, *, login: str,
                      server: str, terminal_data_path: str | None = None,
                      now: float | None = None) -> dict[str, Any]:
    """Read clock evidence independently of calendar event availability.

    Legacy schema 1 identifies the account/server, not a unique terminal.
    When a publisher includes terminal_data_path it must match too. The gateway
    additionally corroborates this reference with its own live terminal tick.
    """
    unavailable = {"ok": False, "source": "mql5_clock_snapshot",
                   "code": "clock_unavailable", "severity": "transient"}

    def fail(detail, code="clock_invalid", severity="hard"):
        return {**unavailable, "detail": detail, "code": code, "severity": severity}

    if not commondata_path or not login or not server:
        return fail("Identidade ou diretório comum do MT5 indisponível.",
                    "clock_unavailable", "transient")
    try:
        terminal_root = Path(terminal_data_path).resolve() if terminal_data_path else None
        dedicated = bool(terminal_root and (
            (terminal_root / "MQL5" / "Files" / CLOCK_FILE).exists() or
            (terminal_root / "MQL5" / "Services" / "ScalperLabClockService.ex5").exists()))
        root = ((terminal_root / "MQL5" / "Files") if dedicated else
                (Path(commondata_path) / "Files")).resolve()
        path = (root / (CLOCK_FILE if dedicated else BRIDGE_FILE)).resolve()
        if not path.is_relative_to(root):
            return fail("Caminho da ponte MQL5 inválido.")
        with path.open("rb") as stream:
            data = stream.read(MAX_BRIDGE_BYTES + 1)
        if len(data) > MAX_BRIDGE_BYTES:
            return fail("Snapshot do relógio MQL5 excede o limite permitido.")
        payload = json.loads(data.decode("utf-8-sig"))
        if not isinstance(payload, dict) or payload.get("schema") != (2 if dedicated else 1):
            return fail("Estrutura do relógio MQL5 incompatível.")
        if dedicated and (payload.get("provider") != "ScalperLabClockService" or
                          payload.get("version") != "2.00" or not payload.get("terminal_data_path")):
            return fail("Identidade ou versão do ScalperLabClockService incompatível.")
        if dedicated and payload.get("connected") is not True:
            return fail("ScalperLabClockService ativo; terminal sem conexão com a corretora.",
                        "clock_disconnected", "transient")
        if (str(payload.get("account_login", "")) != str(login)
                or payload.get("account_server") != server):
            return fail("Relógio MQL5 pertence a outra conta/servidor.", "clock_identity")
        published_path = payload.get("terminal_data_path")
        if published_path and (not terminal_data_path or
                Path(published_path).resolve() != Path(terminal_data_path).resolve()):
            return fail("Relógio MQL5 pertence a outro terminal.", "clock_identity")
        captured = payload.get("captured_at_epoch")
        offset = payload.get("server_utc_offset_seconds")
        if (isinstance(captured, bool) or not isinstance(captured, (int, float))
                or not math.isfinite(captured) or captured <= 0):
            return fail("Data de captura do relógio MQL5 inválida.")
        current = time.time() if now is None else now
        age = current - captured
        if not math.isfinite(age) or age < -5:
            return fail("Snapshot do relógio MQL5 está no futuro.")
        if age > (CLOCK_MAX_AGE_SECONDS if dedicated else MAX_AGE_SECONDS):
            return fail((f"ScalperLabClockService sem atualização há {int(age)} s; inicie o serviço no terminal selecionado."
                         if dedicated else "Relógio MQL5 legado desatualizado; instale e inicie ScalperLabClockService."),
                        "clock_stale", "transient")
        if (isinstance(offset, bool) or not isinstance(offset, int) or abs(offset) > 50400):
            return fail("Offset do serviço MQL5 inválido; valor não será ajustado.")
        # Consecutive TimeTradeServer/TimeGMT calls may straddle a second.
        canonical = round(offset / 900) * 900
        if abs(offset - canonical) > 5:
            return fail("Relógios MQL5 divergem da tolerância de cinco segundos.")
        server_epoch = datetime.strptime(payload["trade_server_time"], "%Y.%m.%d %H:%M:%S").replace(
            tzinfo=timezone.utc).timestamp()
        if abs(server_epoch - captured - offset) > 2:
            return fail("Horário do servidor e offset MQL5 inconsistentes.")
        return {"ok": True, "source": "mql5_clock_snapshot",
                "publisher": "ScalperLabClockService" if dedicated else "legacy_calendar",
                "publisher_version": payload.get("version"),
                "heartbeat_interval_seconds": 10 if dedicated else 60,
                "identity_scope": "terminal" if published_path else "account_server",
                "server_utc_offset_seconds": canonical, "reported_offset_seconds": offset,
                "captured_at_epoch": captured, "snapshot_age_seconds": round(age, 3)}
    except (OSError, UnicodeError) as exc:
        return fail(f"Publicação do relógio indisponível ({type(exc).__name__}); inicie ScalperLabClockService no MT5 selecionado.",
                    "clock_unavailable", "transient")
    except (ValueError, TypeError, KeyError, OverflowError):
        return fail("Não foi possível validar o snapshot do relógio MQL5.")


def read_calendar_export(commondata_path: str | Path | None, *, login: str,
                         server: str, now: float | None = None) -> dict[str, Any]:
    """Read the local, read-only MQL5 calendar export for the currently connected account."""
    unavailable = {"status": "unavailable", "provider": "MetaTrader 5 Economic Calendar",
                   "events": [], "detail": "Ponte MQL5 do calendário não está instalada ou ainda não publicou dados."}
    if not commondata_path or not login or not server:
        return unavailable
    root = Path(commondata_path).expanduser()
    path = (root / "Files" / BRIDGE_FILE).resolve()
    try:
        files_root = (root / "Files").resolve()
        if not path.is_relative_to(files_root) or not path.is_file():
            return unavailable
        if path.stat().st_size > MAX_BRIDGE_BYTES:
            return {**unavailable, "detail": "Exportação do calendário excede o limite permitido."}
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            return {**unavailable, "detail": "Versão ou estrutura da exportação MQL5 incompatível."}
        if str(payload.get("account_login", "")) != str(login) or payload.get("account_server") != server:
            return {**unavailable, "detail": "Exportação do calendário pertence a outra conta/servidor MT5."}
        captured = float(payload.get("captured_at_epoch", 0))
        age = (time.time() if now is None else now) - captured
        if payload.get("status") != "available":
            error_code = _bounded_int(payload.get("error_code"), 0, 2_147_483_647)
            return {**unavailable, "status": "unavailable",
                    "detail": f"Calendário do MT5 indisponível nesta consulta (código {error_code if error_code is not None else 'desconhecido'})."}
        if captured <= 0 or age < -60 or age > MAX_AGE_SECONDS:
            return {**unavailable, "status": "stale",
                    "detail": "Calendário MQL5 atrasado; resultados não serão usados na análise.",
                    "age_seconds": max(0, int(age)) if age >= 0 else None}
        raw_events = payload.get("events")
        if not isinstance(raw_events, list) or len(raw_events) > MAX_EVENTS:
            return {**unavailable, "detail": "Lista de eventos inválida ou acima do limite."}
        events = []
        for row in raw_events:
            if not isinstance(row, dict):
                continue
            event_id = row.get("event_id")
            value_id = row.get("value_id")
            name = row.get("name")
            currency = row.get("currency")
            event_time = row.get("event_time_server")
            if (not isinstance(event_id, int) or not isinstance(value_id, int)
                    or not isinstance(name, str) or not isinstance(currency, str)
                    or not isinstance(event_time, str)):
                continue
            events.append({
                "event_id": event_id, "value_id": value_id,
                "name": name[:300], "currency": currency[:8].upper(),
                "country": str(row.get("country", ""))[:100],
                "importance": row.get("importance") if row.get("importance") in (0, 1, 2, 3) else 0,
                "event_time_server": event_time[:32],
                "seconds_from_capture": int(row.get("seconds_from_capture", 0)),
                "actual": _finite_number(row.get("actual")),
                "forecast": _finite_number(row.get("forecast")),
                "previous": _finite_number(row.get("previous")),
                "revised_previous": _finite_number(row.get("revised_previous")),
                "source_url": str(row.get("source_url", ""))[:1000],
                "impact_type": row.get("impact_type") if row.get("impact_type") in (0, 1, 2) else 0,
            })
        return {
            "status": "available", "provider": "MetaTrader 5 Economic Calendar",
            "detail": "Calendário do terminal recebido; horários permanecem no fuso do servidor MT5.",
            "captured_at_utc": payload.get("captured_at_utc"),
            "trade_server_time": str(payload.get("trade_server_time", ""))[:32],
            "server_utc_offset_seconds": _bounded_int(payload.get("server_utc_offset_seconds"), -86400, 86400),
            "age_seconds": max(0, int(age)), "time_basis": "trade_server",
            "events": events,
        }
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        return {**unavailable, "detail": "Não foi possível ler/validar a exportação local do calendário."}


def calendar_context_for_symbol(calendar: dict[str, Any], currencies: set[str]) -> dict[str, Any]:
    """Filter calendar records to instrument currencies without converting events into a trade bias."""
    status = calendar.get("status", "unavailable")
    if status != "available":
        return {"status": status, "bias": "unknown", "detail": calendar.get("detail", "Calendário indisponível."),
                "provider": calendar.get("provider", "MetaTrader 5 Economic Calendar"), "events": [],
                "time_basis": calendar.get("time_basis", "trade_server")}
    relevant = [event for event in calendar.get("events", [])
                if str(event.get("currency", "")).upper() in currencies]
    relevant.sort(key=lambda event: event.get("seconds_from_capture", 0))
    upcoming = [event for event in relevant if event.get("seconds_from_capture", 0) >= 0]
    status_detail = (f"Calendário MT5: {len(upcoming)} evento(s) futuro(s) relacionado(s) a "
                     f"{', '.join(sorted(currencies)) or 'nenhuma moeda mapeada'}; "
                     "feed de notícias e séries macro ainda não integrados. Os eventos são contexto, não viés direcional.")
    return {"status": "partial", "bias": "unknown", "detail": status_detail,
            "provider": calendar.get("provider"), "captured_at_utc": calendar.get("captured_at_utc"),
            "age_seconds": calendar.get("age_seconds"), "time_basis": "trade_server",
            "currencies": sorted(currencies), "events": upcoming[:12]}


def _finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and abs(number) != float("inf") else None


def _bounded_int(value: Any, minimum: int, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return max(minimum, min(maximum, value))
