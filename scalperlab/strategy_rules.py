from __future__ import annotations

from datetime import datetime, timezone
from datetime import time as wall_time
from typing import Any
from zoneinfo import ZoneInfo

STRATEGY_TYPES = {
    "Momentum cross-sectional de moedas (literatura)": "cross_sectional_momentum",
    "Momentum de séries temporais em futuros (literatura)": "time_series_momentum",
    "Carry trade FX com controle fora da amostra": "broker_swap_carry",
    "Reversão de gap de fim de semana em FX": "weekend_gap_reversal",
    "Rompimento da faixa de abertura de Londres (ORB FX)": "opening_range_breakout",
}


def average_true_range(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    ordered = sorted(bars, key=lambda item: item["time"])
    if len(ordered) < period + 1:
        return None
    ranges = []
    for previous, current in zip(ordered[-period - 1:-1], ordered[-period:], strict=True):
        ranges.append(max(current["high"] - current["low"],
                          abs(current["high"] - previous["close"]),
                          abs(current["low"] - previous["close"])))
    return sum(ranges) / period if ranges else None


def time_series_momentum(bars: list[dict[str, Any]], lookback: int) -> dict[str, Any]:
    ordered = sorted(bars, key=lambda item: item["time"])
    if lookback < 2 or len(ordered) < lookback + 1:
        return {"phase": "dados_incompletos", "detail": f"São necessárias {lookback + 1} barras D1 fechadas."}
    first, last = ordered[-lookback - 1], ordered[-1]
    change = last["close"] / first["close"] - 1 if first["close"] else 0
    if change == 0:
        return {"phase": "sem_sinal", "detail": "Retorno do período igual a zero; sem operação."}
    atr = average_true_range(ordered, 14)
    if not atr:
        return {"phase": "dados_incompletos", "detail": "Histórico insuficiente para ATR D1 e stop."}
    return {"phase": "sinal", "side": "BUY" if change > 0 else "SELL",
            "stop_distance": 2.0 * atr, "signal_value": change,
            "detail": "Direção pelo retorno próprio das últimas barras D1 fechadas; stop a 2 ATR."}


def cross_sectional_currency_momentum(
    markets: dict[str, dict[str, Any]], lookback: int,
) -> dict[str, Any]:
    scores: dict[str, float] = {}
    counts: dict[str, int] = {}
    returns: dict[str, float] = {}
    for symbol, market in markets.items():
        base, quote = market["contract"].get("currency_base"), market["contract"].get("currency_profit")
        if not (isinstance(base, str) and len(base) == 3 and base.isalpha()
                and isinstance(quote, str) and len(quote) == 3 and quote.isalpha()):
            continue
        bars = sorted(market["bars"], key=lambda item: item["time"])
        if not base or not quote or len(bars) < lookback + 1 or bars[-lookback - 1]["close"] <= 0:
            continue
        ret = bars[-1]["close"] / bars[-lookback - 1]["close"] - 1.0
        returns[symbol] = ret
        scores[base] = scores.get(base, 0.0) + ret
        scores[quote] = scores.get(quote, 0.0) - ret
        counts[base] = counts.get(base, 0) + 1
        counts[quote] = counts.get(quote, 0) + 1
    scores = {currency: score / counts[currency] for currency, score in scores.items() if counts[currency] >= 1}
    if len(scores) < 2:
        return {"phase": "dados_incompletos", "detail": "Informe ao menos três pares FX com moedas conectadas entre si e histórico D1."}
    strongest, weakest = max(scores, key=scores.get), min(scores, key=scores.get)
    if strongest == weakest or scores[strongest] <= scores[weakest]:
        return {"phase": "sem_sinal", "detail": "As pontuações de força relativa não separam moedas neste período."}
    for symbol, market in markets.items():
        contract = market["contract"]
        base, quote = contract.get("currency_base"), contract.get("currency_profit")
        if (base, quote) == (strongest, weakest):
            side = "BUY"
        elif (base, quote) == (weakest, strongest):
            side = "SELL"
        else:
            continue
        atr = average_true_range(market["bars"], 14)
        if not atr:
            continue
        return {"phase": "sinal", "side": side, "symbol": symbol,
                "stop_distance": 2.0 * atr, "signal_value": scores[strongest] - scores[weakest],
                "detail": f"Long {strongest}/short {weakest}; ranking médio de retornos {lookback} D1; stop 2 ATR."}
    return {"phase": "sem_sinal", "detail": f"Moedas fortes/fracas: {strongest}/{weakest}, mas não há par direto no universo informado."}


def broker_swap_carry(market: dict[str, Any]) -> dict[str, Any]:
    contract = market["contract"]
    long_swap = float(contract.get("swap_long", 0.0))
    short_swap = float(contract.get("swap_short", 0.0))
    best = max(long_swap, short_swap)
    if best <= 0:
        return {"phase": "sem_sinal", "detail": "Nenhuma direção apresenta swap positivo neste contrato; carry bloqueado."}
    atr = average_true_range(market["bars"], 14)
    if not atr:
        return {"phase": "dados_incompletos", "detail": "Histórico D1 insuficiente para definir stop de volatilidade."}
    return {"phase": "sinal", "side": "BUY" if long_swap >= short_swap else "SELL",
            "stop_distance": 2.0 * atr, "signal_value": best,
            "detail": "Direção selecionada pelo maior swap informado pelo broker; stop 2 ATR. É uma adaptação de carry via swap, não a carteira forward dos estudos."}


def weekend_gap_reversal(
    intraday_bars: list[dict[str, Any]], daily_bars: list[dict[str, Any]],
    *, now: datetime, timezone_name: str, gap_atr_multiple: float, reward_risk: float,
) -> dict[str, Any]:
    if len(intraday_bars) < 1:
        return {"phase": "dados_incompletos", "detail": "Sem barras intradiárias do símbolo FX."}
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    # FX spot normally reopens on Sunday evening in New York; use an explicit
    # local session boundary and DST-aware timezone, not a fixed UTC offset.
    days_since_sunday = (local_now.weekday() + 1) % 7
    sunday = local_now.date().fromordinal(local_now.date().toordinal() - days_since_sunday)
    open_at = datetime.combine(sunday, wall_time(17, 0), tzinfo=zone)
    friday = sunday.fromordinal(sunday.toordinal() - 2)
    friday_cutoff = datetime.combine(friday, wall_time(17, 0), tzinfo=zone)
    if local_now < open_at or (local_now - open_at).total_seconds() > 15 * 60:
        return {"phase": "aguardando_reabertura", "detail": "A regra só observa os primeiros 15 minutos após a reabertura semanal de domingo, 17:00 Nova York."}
    if local_now.weekday() != 6:
        return {"phase": "janela_perdida", "detail": "A janela de entrada do gap semanal já passou; não entrar atrasado."}
    ordered = sorted(intraday_bars, key=lambda item: item["time"])
    friday_rows, open_rows = [], []
    for bar in ordered:
        moment = datetime.fromtimestamp(bar["time"], timezone.utc).astimezone(zone)
        if moment.date() == friday and moment < friday_cutoff:
            friday_rows.append((moment, bar))
        if moment >= open_at and moment <= local_now:
            open_rows.append((moment, bar))
    if not friday_rows or not open_rows:
        return {"phase": "dados_incompletos", "detail": "Não foi possível localizar fechamento de sexta e primeiro candle da reabertura."}
    first_open_time, first_open = open_rows[0]
    if (local_now - first_open_time).total_seconds() > 15 * 60:
        return {"phase": "janela_perdida", "detail": "Primeiro candle da reabertura está fora da janela de 15 minutos."}
    atr = average_true_range(daily_bars, 14)
    if not atr:
        return {"phase": "dados_incompletos", "detail": "Histórico D1 insuficiente para estimar ATR do gap."}
    friday_close = friday_rows[-1][1]["close"]
    reopen = first_open["open"]
    gap = reopen - friday_close
    if abs(gap) < gap_atr_multiple * atr:
        return {"phase": "sem_sinal", "detail": "Gap semanal menor que o limite configurado em múltiplos de ATR."}
    # Avoid entering a fade if the target was already touched before evaluation.
    if gap > 0 and min(bar["low"] for _, bar in open_rows) <= friday_close:
        return {"phase": "janela_perdida", "detail": "O preço já retornou ao fechamento de sexta antes da avaliação; não perseguir entrada atrasada."}
    if gap < 0 and max(bar["high"] for _, bar in open_rows) >= friday_close:
        return {"phase": "janela_perdida", "detail": "O preço já retornou ao fechamento de sexta antes da avaliação; não perseguir entrada atrasada."}
    side = "SELL" if gap > 0 else "BUY"
    return {"phase": "sinal", "side": side, "target_price": friday_close,
            "stop_distance": abs(gap) / reward_risk, "signal_value": gap / atr,
            "session_key": sunday.isoformat(),
            "detail": "Fade do gap de reabertura; alvo no fechamento de sexta, stop dimensionado pelo múltiplo R configurado."}
