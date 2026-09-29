from __future__ import annotations

import base64
import ctypes
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_NTP_OFFSET_SECONDS = 2.0
MAX_CLOCK_CHECK_AGE_SECONDS = 15 * 60
CLOCK_MONITOR_INTERVAL_SECONDS = 4 * 60
CLOCK_MONITOR_RETRY_SECONDS = 45


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SystemClockService:
    """Check the Windows time service and MT5 UTC calibration before execution."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.validation_lock = threading.RLock()
        self._verified_monotonic: float | None = None
        self._monitor_enabled = False
        self._monitor_status = "idle"
        self._last_auto_check_at: str | None = None
        self._next_auto_check_monotonic: float | None = None
        self._state: dict[str, Any] = {
            "status": "not_checked",
            "detail": "Valide o horário do Windows e do MT5 antes de iniciar uma execução.",
            "checked_at": None,
            "source": None,
            "ntp_offset_seconds": None,
            "service_running": None,
            "startup_type": None,
            "mt5_status": "not_checked",
            "mt5_detail": None,
            "mt5_symbols_checked": 0,
            "mt5_symbols_total": 0,
            "mt5_server_utc_offset_seconds": None,
            "mt5_terminal_id": None,
            "mt5_account_fingerprint": None,
            "mt5_symbols": [],
            "mt5_tick_diagnostics": [],
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            age = self._proof_age_locked()
            if self._state["status"] == "synchronized":
                if age is None or age > MAX_CLOCK_CHECK_AGE_SECONDS:
                    self._state.update(
                        status="expired", mt5_status="expired",
                        detail=("A validação UTC venceu; o monitor está tentando confirmar "
                                "o horário novamente. Nenhuma nova ordem será enviada."),
                    )
            result = dict(self._state)
            result.update({
                "monitor_enabled": self._monitor_enabled,
                "monitor_status": self._monitor_status,
                "last_auto_check_at": self._last_auto_check_at,
                "next_check_in_seconds": self._next_check_in_locked(),
                "proof_age_seconds": round(age, 1) if age is not None else None,
                "proof_expires_in_seconds": (max(0, round(MAX_CLOCK_CHECK_AGE_SECONDS - age, 1))
                                              if age is not None else None),
            })
            return result

    def _proof_age_locked(self) -> float | None:
        if self._verified_monotonic is None:
            return None
        age = time.monotonic() - self._verified_monotonic
        return age if age >= 0 else None

    def _next_check_in_locked(self) -> int | None:
        if self._next_auto_check_monotonic is None:
            return None
        return max(0, round(self._next_auto_check_monotonic - time.monotonic()))

    def monitor_should_run(self) -> bool:
        with self._lock:
            return self._monitor_enabled

    def seconds_until_monitor_check(self, idle_seconds: float = 15.0) -> float:
        with self._lock:
            if not self._monitor_enabled or self._next_auto_check_monotonic is None:
                return max(1.0, idle_seconds)
            return max(0.0, self._next_auto_check_monotonic - time.monotonic())

    def apply_periodic_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Record a read-only health probe without silently arming an execution engine."""
        now_monotonic = time.monotonic()
        with self._lock:
            if not self._monitor_enabled:
                return {"applied": False, "event": None, "next_delay_seconds": 15}

            before_status = self._state.get("status")
            before_monitor = self._monitor_status
            self._last_auto_check_at = _utc_now()
            self._state["mt5_tick_diagnostics"] = result.get("mt5_tick_diagnostics", [])
            if result.get("invalidate"):
                detail = str(result.get("detail") or "A conta ou o terminal MT5 mudou.")
                self._verified_monotonic = None
                self._monitor_enabled = False
                self._monitor_status = "idle"
                self._next_auto_check_monotonic = None
                self._state.update(status="not_checked", mt5_status="not_checked",
                                   detail=detail, checked_at=None, mt5_detail=detail,
                                   mt5_terminal_id=None, mt5_account_fingerprint=None,
                                   mt5_symbols=[], mt5_symbols_checked=0,
                                   mt5_symbols_total=0)
                return {"applied": True, "event": "identity_changed", "detail": detail,
                        "status": "not_checked", "next_delay_seconds": 15}
            severity = str(result.get("severity", "transient"))
            if result.get("ok"):
                self._state.update(
                    status="synchronized", mt5_status="verified",
                    detail="Horário UTC revalidado automaticamente no Windows e no MT5.",
                    checked_at=self._last_auto_check_at,
                    source=result.get("source"),
                    ntp_offset_seconds=result.get("ntp_offset_seconds"),
                    service_running=result.get("service_running"),
                    startup_type=result.get("startup_type"),
                    mt5_detail=result.get("mt5_detail"),
                    mt5_symbols_checked=result.get("mt5_symbols_checked", 0),
                    mt5_symbols_total=result.get("mt5_symbols_total", 0),
                    mt5_server_utc_offset_seconds=result.get("mt5_server_utc_offset_seconds"),
                    mt5_terminal_id=result.get("terminal_id"),
                    mt5_account_fingerprint=result.get("account_fingerprint"),
                    mt5_symbols=result.get("symbols", []),
                )
                self._verified_monotonic = now_monotonic
                self._monitor_status = "healthy"
                self._next_auto_check_monotonic = now_monotonic + CLOCK_MONITOR_INTERVAL_SECONDS
                event = ("recovered" if before_status != "synchronized" or before_monitor == "retrying"
                         else None)
                delay = CLOCK_MONITOR_INTERVAL_SECONDS
            elif severity == "hard":
                self._state.update(
                    status="error", mt5_status=result.get("mt5_status", "error"),
                    detail=str(result.get("detail") or "A validação UTC encontrou divergência."),
                    mt5_detail=result.get("mt5_detail", result.get("detail")),
                )
                self._monitor_status = "blocked"
                self._next_auto_check_monotonic = now_monotonic + CLOCK_MONITOR_RETRY_SECONDS
                event = ("blocked" if before_status != "error" or before_monitor != "blocked"
                         else None)
                delay = CLOCK_MONITOR_RETRY_SECONDS
            else:
                self._state["mt5_detail"] = result.get("mt5_detail", result.get("detail"))
                age = self._proof_age_locked()
                still_valid = (age is not None and age <= MAX_CLOCK_CHECK_AGE_SECONDS
                               and before_status == "synchronized"
                               and before_monitor != "blocked")
                if still_valid:
                    self._state.update(
                        status="synchronized", mt5_status="verified",
                        detail=("A revalidação automática não respondeu; a última confirmação "
                                f"continua válida por até {max(0, int(MAX_CLOCK_CHECK_AGE_SECONDS - age))} s. "
                                "Nova tentativa automática programada."),
                    )
                else:
                    self._state.update(
                        status="expired", mt5_status="expired",
                        detail=("A validação UTC venceu e a revalidação automática ainda não "
                                "foi confirmada. Nenhuma nova ordem será enviada."),
                    )
                self._monitor_status = "retrying"
                self._next_auto_check_monotonic = now_monotonic + CLOCK_MONITOR_RETRY_SECONDS
                event = ("retrying" if before_monitor != "retrying" else None)
                if not still_valid and before_status != "expired":
                    event = "expired"
                delay = CLOCK_MONITOR_RETRY_SECONDS

            return {"applied": True, "event": event,
                    "detail": result.get("detail", self._state.get("detail")),
                    "status": self._state.get("status"),
                    "next_delay_seconds": delay}

    def is_verified(self, *, terminal_id: str | None = None,
                    account_fingerprint: str | None = None) -> bool:
        with self.validation_lock:
            return self._is_verified(terminal_id=terminal_id,
                                    account_fingerprint=account_fingerprint)

    def _is_verified(self, *, terminal_id: str | None = None,
                     account_fingerprint: str | None = None) -> bool:
        state = self.snapshot()
        if state["status"] != "synchronized" or state["mt5_status"] != "verified":
            return False
        if terminal_id is not None and state.get("mt5_terminal_id") != terminal_id:
            return False
        if (account_fingerprint is not None
                and state.get("mt5_account_fingerprint") != account_fingerprint):
            return False
        checked_at = state.get("checked_at")
        if not checked_at:
            return False
        try:
            datetime.fromisoformat(checked_at)
        except (TypeError, ValueError):
            return False
        with self._lock:
            age = self._proof_age_locked()
        if age is None or age > MAX_CLOCK_CHECK_AGE_SECONDS:
            return False
        try:
            diagnostics = self._inspect()
        except Exception:
            diagnostics = {"ok": False,
                           "detail": "Falha ao revalidar a fonte UTC do Windows."}
        if not diagnostics.get("ok"):
            detail = diagnostics.get("detail") or "A fonte UTC não confirmou a sincronização atual."
            with self._lock:
                self._state.update(status="error", mt5_status="error",
                                   detail=f"Revalidação UTC falhou: {detail}",
                                   mt5_detail=detail)
                if self._monitor_enabled:
                    self._monitor_status = "blocked"
                    self._next_auto_check_monotonic = (
                        time.monotonic() + CLOCK_MONITOR_RETRY_SECONDS
                    )
            return False
        return True

    def is_currently_verified(self, *, terminal_id: str | None = None,
                              account_fingerprint: str | None = None) -> bool:
        """Check the cached proof's age and identity without making an NTP network call.

        Use this inside execution cycles. A fresh NTP measurement belongs to the
        explicit start/verification flow; repeating `w32tm /stripchart` every few
        seconds would stall signal evaluation and delay preflight checks.
        """
        state = self.snapshot()
        if state["status"] != "synchronized" or state["mt5_status"] != "verified":
            return False
        if terminal_id is not None and state.get("mt5_terminal_id") != terminal_id:
            return False
        if (account_fingerprint is not None
                and state.get("mt5_account_fingerprint") != account_fingerprint):
            return False
        checked_at = state.get("checked_at")
        if not checked_at:
            return False
        try:
            checked = datetime.fromisoformat(checked_at)
        except (TypeError, ValueError):
            return False
        with self._lock:
            age = self._proof_age_locked()
        return age is not None and age <= MAX_CLOCK_CHECK_AGE_SECONDS

    def verify_and_synchronize(self) -> dict[str, Any]:
        with self.validation_lock:
            return self._verify_and_synchronize()

    def verify_read_only(self) -> dict[str, Any]:
        """Establish a new proof without repairing Windows Time or changing the clock."""
        with self.validation_lock:
            return self._verify_and_synchronize(repair=False)

    def inspect_read_only(self) -> dict[str, Any]:
        """Measure Windows Time/NTP state without repairing or changing the clock."""
        if os.name != "nt":
            return {"ok": False,
                    "detail": "A verificação automática do Windows Time só está disponível no Windows."}
        try:
            return self._inspect()
        except Exception as exc:
            return {"ok": False,
                    "detail": f"Falha ao consultar o Windows Time ({type(exc).__name__})."}

    def _verify_and_synchronize(self, *, repair: bool = True) -> dict[str, Any]:
        # A manual validation starts a new proof lifecycle. Pause the periodic
        # monitor and discard the previous lease until Windows and MT5 both
        # confirm the new measurement.
        with self._lock:
            self._verified_monotonic = None
            self._monitor_enabled = False
            self._monitor_status = "idle"
            self._last_auto_check_at = None
            self._next_auto_check_monotonic = None
        if os.name != "nt":
            return self._set_state(
                status="unsupported",
                detail="A verificação automática do Windows Time só está disponível no Windows.",
                checked_at=_utc_now(),
                mt5_status="not_checked",
            )

        self._set_state(status="checking", detail="Verificando serviço do Windows e fonte UTC…",
                        checked_at=None, mt5_status="checking", mt5_detail=None,
                        mt5_symbols_checked=0, mt5_symbols_total=0,
                        mt5_server_utc_offset_seconds=None, source=None,
                        mt5_terminal_id=None, mt5_account_fingerprint=None,
                        ntp_offset_seconds=None, service_running=None, startup_type=None)
        diagnostics = self._inspect()
        if not diagnostics["ok"] and repair:
            repair_result = self._repair(diagnostics)
            if not repair_result["ok"]:
                return self._set_state(
                    status="error", detail=repair_result["detail"], checked_at=_utc_now(),
                    service_running=repair_result.get("service_running"),
                    startup_type=repair_result.get("startup_type"),
                    source=diagnostics.get("source"),
                    ntp_offset_seconds=diagnostics.get("ntp_offset_seconds"),
                    mt5_status="not_checked", mt5_detail=None,
                )
            diagnostics = self._inspect()

        if not diagnostics["ok"]:
            return self._set_state(
                status="error", detail=diagnostics["detail"], checked_at=_utc_now(),
                service_running=diagnostics.get("service_running"),
                startup_type=diagnostics.get("startup_type"),
                source=diagnostics.get("source"),
                ntp_offset_seconds=diagnostics.get("ntp_offset_seconds"),
                mt5_status="not_checked", mt5_detail=None,
            )

        return self._set_state(
            status="system_synchronized",
            detail="Windows sincronizado. Confirmando o relógio do terminal MT5…",
            checked_at=_utc_now(), source=diagnostics["source"],
            ntp_offset_seconds=diagnostics["ntp_offset_seconds"],
            service_running=diagnostics["service_running"],
            startup_type=diagnostics["startup_type"],
            mt5_status="checking", mt5_detail=None,
        )

    def set_mt5_result(self, *, verified: bool, detail: str,
                       symbols_checked: int, symbols_total: int,
                       server_utc_offset_seconds: int | None,
                       terminal_id: str | None = None,
                       account_fingerprint: str | None = None,
                       symbols: list[str] | None = None,
                       tick_diagnostics: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        current = self.snapshot()
        if current["status"] != "system_synchronized":
            return current
        return self._set_state(
            status="synchronized" if verified else "mt5_unverified",
            detail=("Horário sincronizado e UTC confirmado no Windows e no MT5."
                    if verified else
                    "O Windows está sincronizado, mas o UTC do MT5 não foi confirmado."),
            mt5_status="verified" if verified else "unverified",
            mt5_detail=detail, mt5_symbols_checked=symbols_checked,
            mt5_symbols_total=symbols_total,
            mt5_server_utc_offset_seconds=server_utc_offset_seconds,
            mt5_terminal_id=terminal_id,
            mt5_account_fingerprint=account_fingerprint,
            mt5_symbols=list(symbols or []),
            mt5_tick_diagnostics=list(tick_diagnostics or [])[:12],
            monitor_enabled=bool(terminal_id and account_fingerprint),
            monitor_status="healthy" if verified else "retrying",
        )

    def invalidate(self, detail: str) -> dict[str, Any]:
        with self._lock:
            self._verified_monotonic = None
            self._monitor_enabled = False
            self._monitor_status = "idle"
            self._last_auto_check_at = None
            self._next_auto_check_monotonic = None
        return self._set_state(
            status="not_checked", detail=detail, checked_at=None,
            mt5_status="not_checked", mt5_detail=None,
            mt5_symbols_checked=0, mt5_symbols_total=0,
            mt5_server_utc_offset_seconds=None, mt5_terminal_id=None,
            mt5_account_fingerprint=None, mt5_symbols=[], monitor_enabled=False,
            mt5_tick_diagnostics=[],
        )

    def _set_state(self, **updates: Any) -> dict[str, Any]:
        with self._lock:
            self._state.update(updates)
            if "monitor_enabled" in updates:
                self._monitor_enabled = bool(updates["monitor_enabled"])
            if updates.get("status") == "synchronized" and updates.get("mt5_status") == "verified":
                self._verified_monotonic = time.monotonic()
                self._monitor_enabled = bool(
                    updates.get("monitor_enabled", self._state.get("monitor_enabled"))
                    and self._state.get("mt5_terminal_id")
                    and self._state.get("mt5_account_fingerprint")
                )
                self._monitor_status = "healthy"
                self._next_auto_check_monotonic = (
                    self._verified_monotonic + CLOCK_MONITOR_INTERVAL_SECONDS
                )
            elif (self._monitor_enabled and self._next_auto_check_monotonic is None
                  and updates.get("status") in {"mt5_unverified", "error"}):
                self._monitor_status = "retrying"
                self._next_auto_check_monotonic = (
                    time.monotonic() + CLOCK_MONITOR_RETRY_SECONDS
                )
            return dict(self._state)

    @staticmethod
    def _run(args: list[str], timeout: float = 8.0) -> subprocess.CompletedProcess[str]:
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        return subprocess.run(args, capture_output=True, text=True, errors="replace",
                              timeout=timeout, check=False, creationflags=creation_flags)

    def _service_status(self) -> dict[str, Any]:
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            return {"ok": False, "detail": "O Windows PowerShell não está disponível."}
        query = (
            "$s=Get-CimInstance Win32_Service -Filter \"Name='W32Time'\"; "
            "if($null -eq $s){exit 2}; "
            "$c=Get-CimInstance Win32_ComputerSystem; "
            "[pscustomobject]@{state=$s.State;startup_type=$s.StartMode;"
            "domain_member=$c.PartOfDomain} "
            "| ConvertTo-Json -Compress"
        )
        try:
            result = self._run([powershell, "-NoProfile", "-NonInteractive", "-Command", query])
        except (OSError, subprocess.TimeoutExpired):
            return {"ok": False, "detail": "Não foi possível consultar o serviço Windows Time."}
        if result.returncode != 0:
            return {"ok": False, "detail": "Não foi possível consultar o serviço Windows Time."}
        try:
            payload = json.loads(result.stdout.strip())
        except (json.JSONDecodeError, TypeError):
            return {"ok": False,
                    "detail": "O Windows retornou um estado inválido do serviço de horário."}
        return {"ok": True, "running": str(payload.get("state", "")).lower() == "running",
                "startup_type": str(payload.get("startup_type", "unknown")),
                "domain_member": bool(payload.get("domain_member", False))}

    def _time_source(self) -> tuple[str | None, str | None]:
        try:
            result = self._run(["w32tm", "/query", "/source"])
        except (OSError, subprocess.TimeoutExpired):
            return None, "Não foi possível consultar a fonte de horário do Windows."
        source = result.stdout.strip().splitlines()[0].strip() if result.stdout.strip() else ""
        if result.returncode == 0 and source:
            return source, None

        # Some managed Windows installations deny `w32tm /query /source` to a
        # standard user while still exposing the same source in read-only status.
        # Fall back to that status output before considering any repair action.
        try:
            status = self._run(["w32tm", "/query", "/status"])
        except (OSError, subprocess.TimeoutExpired):
            status = None
        if status and status.returncode == 0:
            match = re.search(r"^\s*(?:Source|Fonte)\s*:\s*(.+?)\s*$", status.stdout,
                              flags=re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(1), None

        detail = result.stderr.strip() or result.stdout.strip()
        return None, detail or "O Windows não informou uma fonte de horário sincronizada."

    @staticmethod
    def _source_host(source: str) -> str | None:
        host = source.split(",", 1)[0].strip()
        local_sources = {"local cmos clock", "free-running system clock", "relogio cmos local",
                         "relógio cmos local", "vm ic time synchronization provider"}
        if host.casefold() in local_sources or not re.fullmatch(r"[A-Za-z0-9._:%-]+", host):
            return None
        return host

    def _measure_offset(self, source: str) -> tuple[list[float], str | None]:
        host = self._source_host(source)
        if not host:
            return [], "A fonte configurada não permite medir o desvio UTC diretamente."
        try:
            result = self._run(["w32tm", "/stripchart", f"/computer:{host}",
                                "/samples:3", "/dataonly"], timeout=12.0)
        except subprocess.TimeoutExpired:
            return [], "A fonte UTC não respondeu dentro do prazo. Verifique a rede e a fonte NTP."
        except OSError:
            return [], "A ferramenta de sincronização do Windows não está disponível."
        matches = re.findall(r"([+-])\s*(\d+(?:\.\d+)?)\s*s\b", result.stdout,
                             flags=re.IGNORECASE)
        offsets = [float(value) * (-1.0 if sign == "-" else 1.0)
                   for sign, value in matches]
        if result.returncode != 0 or len(offsets) < 2:
            detail = result.stderr.strip() or result.stdout.strip()
            return [], detail or "Não foi possível obter amostras da fonte UTC configurada."
        return offsets, None

    def _inspect(self) -> dict[str, Any]:
        service = self._service_status()
        if not service.get("ok"):
            return {"ok": False, "detail": service["detail"]}
        base = {"service_running": service["running"],
                "startup_type": service["startup_type"],
                "domain_member": service["domain_member"]}
        if not service["running"]:
            return {**base, "ok": False,
                    "detail": "O serviço Windows Time está parado e precisa ser iniciado."}
        if service["startup_type"].casefold() != "auto" and not service["domain_member"]:
            return {**base, "ok": False,
                    "detail": ("O serviço Windows Time não está configurado para iniciar "
                               "automaticamente.")}
        source, source_error = self._time_source()
        if source_error or not source:
            return {**base, "ok": False,
                    "detail": source_error or "Fonte de horário indisponível."}
        offsets, offset_error = self._measure_offset(source)
        if offset_error:
            return {**base, "ok": False, "source": source, "detail": offset_error}
        offset = sum(offsets) / len(offsets)
        worst_offset = max(abs(value) for value in offsets)
        if worst_offset > MAX_NTP_OFFSET_SECONDS:
            return {**base, "ok": False, "source": source,
                    "ntp_offset_seconds": round(offset, 3),
                    "detail": (f"Desvio UTC acima do limite ({worst_offset:.3f}s). "
                               "O Windows precisa sincronizar novamente.")}
        return {**base, "ok": True, "source": source,
                "ntp_offset_seconds": round(offset, 3)}

    def _repair(self, diagnostics: dict[str, Any]) -> dict[str, Any]:
        domain_member = bool(diagnostics.get("domain_member"))
        needs_admin = (not diagnostics.get("service_running")
                       or (not domain_member
                           and diagnostics.get("startup_type", "").casefold() != "auto"))
        commands: list[list[str]] = []
        if not domain_member and diagnostics.get("startup_type", "").casefold() != "auto":
            commands.append(["sc.exe", "config", "W32Time", "start=", "auto"])
        if not diagnostics.get("service_running"):
            commands.append(["sc.exe", "start", "W32Time"])
        commands.append(["w32tm", "/resync", "/rediscover"])
        direct_ok = True
        direct_error = ""
        for args in commands:
            try:
                result = self._run(args, timeout=10.0)
            except (OSError, subprocess.TimeoutExpired) as exc:
                direct_ok = False
                direct_error = type(exc).__name__
                break
            if result.returncode != 0:
                direct_ok = False
                direct_error = (result.stderr or result.stdout).strip()
                break
        if direct_ok:
            checked = {}
            for _ in range(3):
                time.sleep(1.5)
                checked = self._inspect()
                if checked["ok"]:
                    return {"ok": True}
            direct_error = checked.get("detail", "A fonte UTC ainda está fora do limite.")

        permission_error = bool(re.search(
            r"access is denied|acesso negado|0x80070005|error 5\b|erro 5\b",
            direct_error, flags=re.IGNORECASE))
        if not needs_admin and not permission_error:
            service = self._service_status()
            return {"ok": False,
                    "detail": (f"Não foi possível confirmar a sincronização: "
                               f"{direct_error or 'fonte UTC indisponível'}. "
                               "Verifique a conexão com a fonte NTP e tente novamente."),
                    "service_running": service.get("running"),
                    "startup_type": service.get("startup_type")}

        elevated = self._repair_with_elevation(make_auto=not domain_member)
        if elevated["ok"]:
            checked = self._inspect()
            if checked["ok"]:
                return {"ok": True}
            direct_error = checked["detail"]
        elif elevated.get("cancelled"):
            direct_error = ("A autorização administrativa foi cancelada; nenhuma alteração "
                            "foi confirmada.")
        elif elevated.get("detail"):
            direct_error = elevated["detail"]

        service = self._service_status()
        return {"ok": False,
                "detail": (
                    f"Não foi possível corrigir o horário: "
                    f"{direct_error or 'falha na sincronização'} "
                    "Abra o ScalperLab como administrador ou peça ao administrador "
                    "para habilitar o serviço Windows Time."
                ).strip(),
                "service_running": service.get("running"),
                "startup_type": service.get("startup_type")}

    def _repair_with_elevation(self, *, make_auto: bool) -> dict[str, Any]:
        if os.name != "nt":
            return {"ok": False, "detail": "Elevação administrativa indisponível neste sistema."}
        powershell = (Path(os.environ.get("WINDIR", r"C:\Windows")) /
                      "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe")
        if not powershell.is_file():
            return {"ok": False, "detail": "Windows PowerShell não encontrado para a reparação."}
        marker = Path(tempfile.gettempdir()) / f"scalperlab-clock-{uuid.uuid4().hex}.json"
        marker_encoded = base64.b64encode(str(marker).encode("utf-16le")).decode("ascii")
        configure_startup = (
            "Set-Service -Name W32Time -StartupType Automatic; " if make_auto else ""
        )
        script = (
            "$markerPath=[Text.Encoding]::Unicode.GetString([Convert]::FromBase64String("
            f"'{marker_encoded}')); "
            "$ErrorActionPreference='Stop'; try { "
            + configure_startup
            + "Start-Service -Name W32Time; "
            + "$sync = & w32tm /resync /rediscover 2>&1; "
            + "if ($LASTEXITCODE -ne 0) { throw ($sync -join ' ') }; "
            + "@{ok=$true;detail='Sincronização solicitada.'} | ConvertTo-Json -Compress | "
            + "Set-Content -LiteralPath $markerPath -Encoding UTF8 "
            + "} catch { "
            + "@{ok=$false;detail=$_.Exception.Message} | ConvertTo-Json -Compress | "
            + "Set-Content -LiteralPath $markerPath -Encoding UTF8; exit 1 }"
        )
        encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
        parameters = f"-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}"
        try:
            shell_execute = ctypes.windll.shell32.ShellExecuteW
            shell_execute.restype = ctypes.c_void_p
            result = int(shell_execute(None, "runas", str(powershell), parameters, None, 0) or 0)
        except (AttributeError, OSError, ValueError):
            return {"ok": False,
                    "detail": "Não foi possível solicitar a autorização administrativa do Windows."}
        if result <= 32:
            return {"ok": False, "cancelled": result == 1223,
                    "detail": "O Windows não iniciou a correção administrativa."}
        try:
            deadline = time.monotonic() + 35.0
            while time.monotonic() < deadline:
                if marker.exists():
                    try:
                        outcome = json.loads(marker.read_text(encoding="utf-8-sig"))
                        if outcome.get("ok"):
                            return {"ok": True}
                        return {"ok": False,
                                "detail": str(outcome.get("detail", "Falha administrativa."))}
                    except (OSError, json.JSONDecodeError):
                        pass
                time.sleep(0.25)
            return {"ok": False,
                    "detail": "A correção administrativa não terminou dentro do prazo."}
        finally:
            try:
                marker.unlink(missing_ok=True)
            except OSError:
                pass
