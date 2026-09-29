"""Bar timestamp adaptation, separate from Windows/MT5 clock validation."""
from __future__ import annotations

from .mt5_time import MT5TimeError, MT5_TIMEFRAME_SECONDS


def normalize_bar_times(bars: list[dict], *, m1_open: int, tick_utc: int,
                        server_offset: int, timeframe: str,
                        allow_recent_tail: bool = False) -> tuple[list[dict], dict]:
    """Identify rate encoding from the forming M1 bar and an independent UTC tick.

    Server-time adaptation is deliberately limited to a short uninterrupted
    intraday series. It is NOT a historical timezone rule for replay across
    sessions/DST. UTC input is preserved, regardless of the terminal offset.
    """
    candidates = {offset for offset in (0, server_offset)
                  if 0 <= tick_utc - (m1_open - offset) < 60}
    if len(candidates) != 1:
        raise MT5TimeError("Barra M1 em formação não confirmou a base temporal; aguardando nova leitura.",
                           code="bar_time_unverified")
    applied = candidates.pop()
    original_count = len(bars)
    if not bars:
        raise MT5TimeError("Histórico de candles vazio.", code="bars_unavailable")
    timestamps = [row["time"] for row in bars]
    if any(a >= b for a, b in zip(timestamps, timestamps[1:])):
        raise MT5TimeError("Candles duplicados ou fora de sequência; base histórica não confirmada.",
                           code="bar_time_sequence")
    if applied:
        period = MT5_TIMEFRAME_SECONDS[timeframe]
        if allow_recent_tail and period <= 1800:
            # Indicators may use the actual continuous tail, never invented bars
            # spanning a trading break. Offline replay must retain its full span.
            start = len(bars) - 1
            while (start > 0 and timestamps[start] - timestamps[start - 1] == period
                   and tick_utc - (timestamps[start - 1] - applied) <= 86400):
                start -= 1
            bars = bars[start:]
            timestamps = timestamps[start:]
        # Do not backfill an arbitrary historical span with today's offset.
        if (period > 1800 or timestamps[-1] - timestamps[0] > 86400
                or any(b - a != period for a, b in zip(timestamps, timestamps[1:]))
                or tick_utc - (timestamps[0] - applied) > 86400):
            raise MT5TimeError(
                "Histórico no horário do servidor requer regra histórica de fuso: "
                "conversão automática limitada a candles M1–M30 contínuos das últimas 24 horas.",
                code="historical_timezone_required")
        converted = [{**row, "raw_time": row["time"], "time": row["time"] - applied}
                     for row in bars]
    else:
        converted = [dict(row) for row in bars]
    return converted, {
        "bar_timestamp_basis": "trade_server" if applied else "UTC as returned by MetaTrader 5 Python API",
        "bar_offset_applied_seconds": applied,
        "bar_time_evidence": {"forming_m1_raw": m1_open, "tick_utc": tick_utc,
                              "source": "forming_m1_vs_validated_tick",
                              "scope": "recent_contiguous_intraday" if applied else "api_utc"},
        "historical_timezone_verified": not bool(applied),
        "bars_received": original_count, "bars_used": len(converted),
        "bars_dropped_for_time_validation": original_count - len(converted),
    }
