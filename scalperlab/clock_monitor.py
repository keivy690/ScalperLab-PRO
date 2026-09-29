from __future__ import annotations

import math
import threading
from collections.abc import Callable
from typing import Any

from .mt5_time import MAX_OFFSET_CALIBRATION_RESIDUAL_SECONDS

MAX_MT5_CLOCK_TICK_AGE_SECONDS = 120.0
MAX_MT5_CLOCK_RESIDUAL_SECONDS = MAX_OFFSET_CALIBRATION_RESIDUAL_SECONDS


def inspect_mt5_clock(gateway: Any, symbols: list[str], *, terminal_id: str,
                      account_fingerprint: str) -> dict[str, Any]:
    """Confirm UTC using at least one recent MT5 tick and consistent server offsets."""
    if not symbols:
        return {"ok": False, "severity": "transient",
                "detail": "Nenhum símbolo está disponível para revalidar o UTC do MT5.",
                "mt5_status": "unverified", "mt5_symbols_checked": 0,
                "mt5_symbols_total": 0, "symbols": []}

    valid: list[dict[str, Any]] = []
    unavailable: list[str] = []
    rejected: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    clock_errors: list[str] = []
    for symbol in symbols[:12]:
        try:
            tick = gateway.current_tick(symbol)
        except Exception as exc:
            unavailable.append(f"{symbol}: consulta indisponível ({type(exc).__name__})")
            diagnostics.append({"symbol": symbol, "accepted": False,
                                "reason": unavailable[-1]})
            continue
        diagnostic = {**(tick.get("time_normalization") or {}), "symbol": symbol,
                      "accepted": False, "reason": tick.get("detail"), "code": tick.get("code")}
        diagnostics.append(diagnostic)
        if not tick.get("ok"):
            if tick.get("severity") == "hard":
                clock_errors.append(f"{symbol}: {tick.get('detail')}")
            elif tick.get("code") in {"future_tick", "invalid_timestamp"}:
                rejected.append(f"{symbol}: {tick.get('detail')}")
                continue
            unavailable.append(f"{symbol}: {tick.get('detail') or 'tick indisponível'}")
            continue

        normalization = tick.get("time_normalization") or {}
        age = normalization.get("age_seconds")
        residual = normalization.get("calibration_residual_seconds")
        offset = normalization.get("server_utc_offset_seconds")
        # A normalizer already rejects unsafe timestamps for an individual tick.
        # Such a symbol can be stale or temporarily malformed while the rest of
        # Market Watch is healthy, so reject that sample rather than the whole
        # terminal clock proof. The global Windows/NTP check and cross-sample
        # offset agreement remain fail-closed.
        if normalization.get("basis") != "UTC":
            rejected.append(f"{symbol}: base temporal inválida")
            diagnostic["reason"] = rejected[-1]
            continue
        if (isinstance(age, bool) or not isinstance(age, (int, float))
                or not math.isfinite(age)):
            rejected.append(f"{symbol}: idade do tick inválida")
            diagnostic["reason"] = rejected[-1]
            continue
        if age < -5:
            rejected.append(f"{symbol}: tick futuro")
            diagnostic["reason"] = rejected[-1]
            continue
        if age > MAX_MT5_CLOCK_TICK_AGE_SECONDS:
            unavailable.append(f"{symbol}: sem tick recente")
            diagnostic["reason"] = unavailable[-1]
            continue
        if (isinstance(residual, bool) or not isinstance(residual, (int, float))
                or not math.isfinite(residual)
                or abs(residual) > MAX_MT5_CLOCK_RESIDUAL_SECONDS):
            rejected.append(f"{symbol}: calibração fora da tolerância")
            diagnostic["reason"] = rejected[-1]
            continue
        if isinstance(offset, bool) or not isinstance(offset, int):
            rejected.append(f"{symbol}: offset do servidor inválido")
            diagnostic["reason"] = rejected[-1]
            continue
        valid.append({"symbol": symbol, "offset": offset})
        diagnostic.update(accepted=True, reason="Cotação recente com referência UTC validada.")

    offsets = {item["offset"] for item in valid}
    if len(offsets) > 1 or clock_errors:
        detail = ("Referência do relógio MQL5 inválida: " + clock_errors[0] if clock_errors else
                  "A referência UTC do serviço MQL5 mudou durante a coleta; valide novamente.")
        return {"ok": False, "severity": "hard", "detail": detail,
                "mt5_status": "error", "mt5_detail": detail,
                "mt5_symbols_checked": len(valid), "mt5_symbols_total": len(symbols),
                "mt5_server_utc_offset_seconds": None,
                "mt5_tick_diagnostics": diagnostics,
                "symbols": [item["symbol"] for item in valid]}

    if not valid:
        publication_errors = [d for d in diagnostics if str(d.get("code", "")).startswith("clock_")]
        detail = ("Publicação do relógio MQL5 indisponível; confira ScalperLabClockService."
                  if publication_errors else "Sem cotação recente nos ativos consultados; aguardando atualização do MT5.")
        if unavailable:
            detail += " " + "; ".join(unavailable[:3])
        if rejected:
            detail += " Amostras inválidas ignoradas: " + "; ".join(rejected[:3])
        return {"ok": False, "severity": "hard" if rejected else "transient", "detail": detail,
                "mt5_status": "unverified", "mt5_detail": detail,
                "mt5_symbols_checked": 0, "mt5_symbols_total": len(symbols),
                "mt5_server_utc_offset_seconds": None, "symbols": [],
                "mt5_tick_diagnostics": diagnostics}

    sample_symbols = [item["symbol"] for item in valid]
    detail = f"UTC confirmado por tick recente em {', '.join(sample_symbols)}."
    if unavailable:
        detail += f" {len(unavailable)} ativo(s) sem tick recente foram ignorados."
    if rejected:
        detail += f" {len(rejected)} amostra(s) inválida(s) foram ignoradas."
    return {"ok": True, "severity": "ok", "detail": detail,
            "mt5_tick_diagnostics": diagnostics,
            "mt5_status": "verified", "mt5_detail": detail,
            "mt5_symbols_checked": len(valid), "mt5_symbols_total": len(symbols),
            "mt5_server_utc_offset_seconds": next(iter(offsets)),
            "terminal_id": terminal_id, "account_fingerprint": account_fingerprint,
            "symbols": sample_symbols}


class ClockValidationMonitor:
    """Refresh validated UTC evidence in a background thread without changing system time."""

    def __init__(self, clock: Any, probe: Callable[[], dict[str, Any]], *,
                 on_event: Callable[[str, str], None] | None = None) -> None:
        self.clock = clock
        self.probe = probe
        self.on_event = on_event
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="scalperlab-utc-monitor",
                                            daemon=True)
            self._thread.start()

    def shutdown(self, timeout: float = 14.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=max(0.0, timeout))

    def run_once(self) -> dict[str, Any]:
        if not self.clock.monitor_should_run():
            return {"applied": False, "event": None, "next_delay_seconds": 15}
        try:
            with self.clock.validation_lock:
                result = self.probe()
                applied = self.clock.apply_periodic_result(result)
        except Exception as exc:
            applied = self.clock.apply_periodic_result({
                "ok": False, "severity": "transient",
                "detail": f"Falha temporária no monitor UTC ({type(exc).__name__}).",
            })
        event = applied.get("event")
        if event and self.on_event:
            level = "INFO" if event == "recovered" else "WARN"
            detail = str(applied.get("detail") or "Estado da validação UTC atualizado.")
            try:
                self.on_event(level, detail)
            except Exception:
                pass
        return applied

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self.clock.monitor_should_run():
                self._stop.wait(15.0)
                continue
            delay = self.clock.seconds_until_monitor_check()
            if self._stop.wait(delay):
                break
            if not self.clock.monitor_should_run():
                continue
            self.run_once()
