from __future__ import annotations

import math
import time
from dataclasses import dataclass

SERVER_UTC_OFFSET_QUANTUM_SECONDS = 15 * 60
MAX_SERVER_UTC_OFFSET_SECONDS = 14 * 60 * 60
MAX_TICK_AGE_SECONDS = 120.0
MAX_FUTURE_TIME_SKEW_SECONDS = 5.0
MAX_OFFSET_CALIBRATION_RESIDUAL_SECONDS = 180.0
MT5_TIMEFRAME_SECONDS = {
    "M1": 60, "M2": 120, "M3": 180, "M4": 240, "M5": 300, "M6": 360,
    "M10": 600, "M12": 720, "M15": 900, "M20": 1200, "M30": 1800,
    "H1": 3600, "H2": 7200, "H3": 10800, "H4": 14400, "H6": 21600,
    "H8": 28800, "H12": 43200, "D1": 86400, "W1": 604800,
    "MN1": 2_678_400,
}
MT5_MAX_CLOSED_BAR_AGE_SECONDS = {
    **{name: max(180, 2 * seconds + 60)
       for name, seconds in MT5_TIMEFRAME_SECONDS.items()
       if name not in {"D1", "W1", "MN1"}},
    "D1": 5 * 86_400,
    "W1": 21 * 86_400,
    "MN1": 93 * 86_400,
}


class MT5TimeError(ValueError):
    """Raised when a live MT5 tick cannot safely anchor server timestamps to UTC."""

    def __init__(self, message: str, *, code: str = "invalid_timestamp",
                 diagnostics: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.diagnostics = diagnostics or {}


@dataclass(frozen=True, slots=True)
class NormalizedTickTime:
    utc_time: int
    utc_time_msc: int
    server_utc_offset_seconds: int
    age_seconds: float
    calibration_residual_seconds: float


def normalize_tick_time(raw_time: int | float, raw_time_msc: int | float | None = None,
                        *, server_utc_offset_seconds: int,
                        now_epoch: float | None = None) -> NormalizedTickTime:
    """Apply an independently validated terminal offset; never infer it from a quote.

    The caller validates the MQL5 clock snapshot's age/account and Windows UTC.
    A stale quote cannot change the offset or become recent through rounding.
    """
    now = time.time() if now_epoch is None else float(now_epoch)
    if not math.isfinite(now):
        raise MT5TimeError("Relógio UTC local indisponível.")
    offset = server_utc_offset_seconds
    if (isinstance(offset, bool) or not isinstance(offset, int)
            or abs(offset) > MAX_SERVER_UTC_OFFSET_SECONDS):
        raise MT5TimeError("Offset validado do serviço MQL5 ausente ou inválido.")

    try:
        raw_seconds = float(raw_time)
        raw_milliseconds = float(raw_time_msc) if raw_time_msc is not None else 0.0
    except (TypeError, ValueError, OverflowError) as exc:
        raise MT5TimeError("Timestamp do tick MT5 inválido.") from exc
    if not math.isfinite(raw_seconds) or raw_seconds <= 0:
        raise MT5TimeError("Timestamp do tick MT5 ausente ou inválido.")
    if not math.isfinite(raw_milliseconds) or raw_milliseconds < 0:
        raise MT5TimeError("Timestamp time_msc do tick MT5 inválido.")
    if raw_milliseconds > 0:
        if abs(raw_seconds - raw_milliseconds / 1000.0) > 2.0:
            raise MT5TimeError("Campos time e time_msc do tick MT5 são inconsistentes.")
        observed_server_time = raw_milliseconds / 1000.0
    else:
        observed_server_time = raw_seconds

    normalized_milliseconds = int(round(observed_server_time * 1000.0)) - offset * 1000
    normalized_time = normalized_milliseconds // 1000
    age = now - normalized_milliseconds / 1000.0
    diagnostics = {"raw_time": raw_time, "raw_time_msc": raw_time_msc,
                   "server_utc_offset_seconds": offset, "age_seconds": round(age, 3),
                   "utc_time": normalized_time}
    if age < -MAX_FUTURE_TIME_SKEW_SECONDS:
        raise MT5TimeError("O tick permanece no futuro após a normalização UTC.",
                           code="future_tick", diagnostics=diagnostics)
    if age > MAX_TICK_AGE_SECONDS:
        raise MT5TimeError("Cotação desatualizada; análise e entrada neste ativo aguardam tick recente.",
                           code="stale_tick", diagnostics=diagnostics)

    return NormalizedTickTime(
        utc_time=normalized_time,
        utc_time_msc=normalized_milliseconds,
        server_utc_offset_seconds=offset,
        age_seconds=age,
        calibration_residual_seconds=-age,
    )
