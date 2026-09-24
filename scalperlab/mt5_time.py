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


@dataclass(frozen=True, slots=True)
class NormalizedTickTime:
    utc_time: int
    utc_time_msc: int
    server_utc_offset_seconds: int
    age_seconds: float
    calibration_residual_seconds: float


def normalize_tick_time(raw_time: int | float, raw_time_msc: int | float | None = None,
                        *, now_epoch: float | None = None) -> NormalizedTickTime:
    """Normalize MT5's terminal-clock timestamp using a fresh live tick.

    Some MT5 terminal builds/broker servers expose Unix-shaped timestamps in
    trade-server time. Infer the current server-to-UTC offset from a fresh tick
    and the host UTC clock. The offset is recalculated for each tick, so broker
    DST changes do not leave a cached seasonal offset behind. Stale, malformed,
    or clock-inconsistent ticks fail closed instead of receiving a guessed fix.
    """
    now = time.time() if now_epoch is None else float(now_epoch)
    if not math.isfinite(now):
        raise MT5TimeError("Relógio UTC local indisponível.")

    try:
        raw_seconds = float(raw_time)
        raw_milliseconds = float(raw_time_msc) if raw_time_msc is not None else 0.0
    except (TypeError, ValueError, OverflowError) as exc:
        raise MT5TimeError("Timestamp do tick MT5 inválido.") from exc
    if not math.isfinite(raw_seconds) or raw_seconds <= 0:
        raise MT5TimeError("Timestamp do tick MT5 ausente ou inválido.")
    if math.isfinite(raw_milliseconds) and raw_milliseconds > 0:
        if abs(raw_seconds - raw_milliseconds / 1000.0) > 2.0:
            raise MT5TimeError("Campos time e time_msc do tick MT5 são inconsistentes.")
        observed_server_time = raw_milliseconds / 1000.0
    else:
        observed_server_time = raw_seconds

    observed_offset = observed_server_time - now
    offset = int(round(observed_offset / SERVER_UTC_OFFSET_QUANTUM_SECONDS)
                 * SERVER_UTC_OFFSET_QUANTUM_SECONDS)
    if abs(offset) > MAX_SERVER_UTC_OFFSET_SECONDS:
        raise MT5TimeError("Offset do relógio do terminal fora da faixa de fusos reconhecida.")

    residual = observed_offset - offset
    if abs(residual) > MAX_OFFSET_CALIBRATION_RESIDUAL_SECONDS:
        raise MT5TimeError("Tick e relógio local não permitem determinar um offset confiável.")

    normalized_milliseconds = int(round(observed_server_time * 1000.0)) - offset * 1000
    normalized_time = normalized_milliseconds // 1000
    age = now - normalized_milliseconds / 1000.0
    if age < -MAX_FUTURE_TIME_SKEW_SECONDS:
        raise MT5TimeError("O tick permanece no futuro após a normalização UTC.")
    if age > MAX_TICK_AGE_SECONDS:
        raise MT5TimeError("O tick está desatualizado; a análise e a execução foram bloqueadas.")

    return NormalizedTickTime(
        utc_time=normalized_time,
        utc_time_msc=normalized_milliseconds,
        server_utc_offset_seconds=offset,
        age_seconds=age,
        calibration_residual_seconds=residual,
    )
