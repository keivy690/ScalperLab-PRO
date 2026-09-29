from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any

from .config import MT5_SYMBOL_PATTERN
from .market_analyst import TIMEFRAMES_SECONDS, analyze_market, _true_ranges

REPLAY_VERSION = "pullback-sma21-ohlc-v1"
MAX_REPLAY_BARS = 2_500
MIN_VALIDATION_BARS = 200
DEVELOPMENT_FRACTION = 0.70
MIN_HOLDOUT_TRADES_FOR_REVIEW = 30
MAX_REPLAY_TRADES = 500
MAX_SLIPPAGE_POINTS = 100
MAX_CASH_COST_PER_LOT = 10_000.0


class ReplayValidationError(ValueError):
    pass


def _finite(value: Any, field: str, *, minimum: float | None = None,
            maximum: float | None = None) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ReplayValidationError(f"Parâmetro inválido: {field}.") from exc
    if not math.isfinite(result):
        raise ReplayValidationError(f"Parâmetro inválido: {field}.")
    if minimum is not None and result < minimum:
        raise ReplayValidationError(f"{field} está abaixo do mínimo permitido.")
    if maximum is not None and result > maximum:
        raise ReplayValidationError(f"{field} excede o máximo permitido.")
    return result


def _utc_label(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds")


def _rollover_count(start_epoch: int, end_epoch: int) -> int:
    start = datetime.fromtimestamp(start_epoch, UTC).date()
    end = datetime.fromtimestamp(end_epoch, UTC).date()
    return max(0, (end - start).days)


def _momentum_baseline_decision(bars: list[dict[str, Any]], contract: dict[str, Any],
                                point: float) -> dict[str, Any]:
    """Simple causal 20-bar momentum zero-cross baseline with identical trade management."""
    if len(bars) < 22:
        return {"decision": {"order_eligible": False}}
    closes = [float(row["close"]) for row in bars]
    prior_return = closes[-2] / closes[-22] - 1.0
    current_return = closes[-1] / closes[-21] - 1.0
    side = None
    if prior_return <= 0 < current_return:
        side = "BUY"
    elif prior_return >= 0 > current_return:
        side = "SELL"
    if side is None:
        return {"decision": {"order_eligible": False}}

    ranges = _true_ranges(bars)
    if len(ranges) < 14:
        return {"decision": {"order_eligible": False}}
    atr14 = sum(ranges[-14:]) / 14
    latest = bars[-1]
    spread_raw = latest.get("spread")
    if not atr14 or spread_raw is None or float(spread_raw) * point > 0.08 * atr14:
        return {"decision": {"order_eligible": False}}

    reference = closes[-1]
    risk_distance = atr14
    stop = reference - risk_distance if side == "BUY" else reference + risk_distance
    target = reference + 1.5 * risk_distance if side == "BUY" else reference - 1.5 * risk_distance
    return {"decision": {"order_eligible": True, "side": side,
                         "stop": stop, "target": target}}


def _simulate_trade(*, bars: list[dict[str, Any]], signal_index: int,
                    symbol: str, side: str, stop: float, target: float,
                    contract: dict[str, Any], slippage_points: float,
                    commission_per_lot_round_turn: float,
                    swap_long_per_lot_per_utc_rollover: float,
                    swap_short_per_lot_per_utc_rollover: float,
                    volume: float) -> dict[str, Any]:
    point = float(contract["point"])
    tick_size = float(contract.get("trade_tick_size") or point)
    next_bar = bars[signal_index + 1]
    entry_spread_raw = next_bar.get("spread")
    if side == "BUY" and entry_spread_raw is None:
        return {"status": "skipped", "reason": "spread_ausente_no_candle_de_entrada"}
    entry_spread_points = float(entry_spread_raw or 0.0)
    entry_spread = entry_spread_points * point
    slippage = slippage_points * point
    if side == "BUY":
        entry = float(next_bar["open"]) + entry_spread + slippage
        risk_distance = entry - stop
        reward_distance = target - entry
    else:
        entry = float(next_bar["open"]) - slippage
        risk_distance = stop - entry
        reward_distance = entry - target
    if risk_distance <= 0 or reward_distance <= 0:
        return {"status": "skipped", "reason": "gap_invalidou_stop_ou_alvo"}
    if reward_distance / risk_distance < 1.5:
        return {"status": "skipped", "reason": "gap_reduziu_retorno_risco_abaixo_1_5"}

    exit_index: int | None = None
    exit_price: float | None = None
    exit_reason: str | None = None
    same_bar_ambiguous = False
    for index in range(signal_index + 1, len(bars)):
        bar = bars[index]
        spread_raw = bar.get("spread")
        if side == "SELL" and spread_raw is None:
            return {"status": "censored", "reason": "spread_ausente_na_reconstrucao_ask"}
        spread_points = float(spread_raw or 0.0)
        spread = spread_points * point
        bar_open, bar_high, bar_low = (float(bar[key]) for key in ("open", "high", "low"))
        if side == "BUY":
            stop_hit = bar_low <= stop
            target_hit = bar_high >= target
            if stop_hit and target_hit:
                same_bar_ambiguous = True
                fill = bar_open if bar_open <= stop else stop
                exit_price, exit_reason = fill - slippage, "stop_loss_ambos_no_mesmo_candle_stop_primeiro"
            elif stop_hit:
                fill = bar_open if bar_open <= stop else stop
                exit_price, exit_reason = fill - slippage, "stop_loss"
            elif target_hit:
                fill = bar_open if bar_open >= target else target
                exit_price, exit_reason = fill - slippage, "take_profit"
        else:
            ask_open, ask_high, ask_low = bar_open + spread, bar_high + spread, bar_low + spread
            stop_hit = ask_high >= stop
            target_hit = ask_low <= target
            if stop_hit and target_hit:
                same_bar_ambiguous = True
                fill = ask_open if ask_open >= stop else stop
                exit_price, exit_reason = fill + slippage, "stop_loss_ambos_no_mesmo_candle_stop_primeiro"
            elif stop_hit:
                fill = ask_open if ask_open >= stop else stop
                exit_price, exit_reason = fill + slippage, "stop_loss"
            elif target_hit:
                fill = ask_open if ask_open <= target else target
                exit_price, exit_reason = fill + slippage, "take_profit"
        if exit_price is not None:
            exit_index = index
            break

    if exit_index is None:
        return {"status": "censored", "reason": "amostra_terminou_com_posicao_aberta",
                "entry_time_utc": _utc_label(int(next_bar["time"])), "side": side,
                "entry_price": entry, "stop": stop, "target": target}

    entry_epoch = int(next_bar["time"])
    exit_epoch = int(bars[exit_index]["time"])
    rollovers = _rollover_count(entry_epoch, exit_epoch)
    directional_move = (exit_price - entry) if side == "BUY" else (entry - exit_price)
    gross_r_price = directional_move / risk_distance
    tick_value_loss = _finite(contract.get("trade_tick_value_loss", 0.0), "tick_value_loss", minimum=0)
    tick_value_profit = _finite(contract.get("trade_tick_value_profit", 0.0), "tick_value_profit", minimum=0)
    commission_cash = commission_per_lot_round_turn * volume
    swap_per_lot = (swap_long_per_lot_per_utc_rollover if side == "BUY"
                    else swap_short_per_lot_per_utc_rollover)
    swap_cash = swap_per_lot * volume * rollovers
    cash_values_available = tick_size > 0 and tick_value_loss > 0 and tick_value_profit > 0
    if cash_values_available:
        ticks_moved = directional_move / tick_size
        gross_cash = ticks_moved * (tick_value_profit if ticks_moved >= 0 else tick_value_loss) * volume
        risk_cash = (risk_distance / tick_size) * tick_value_loss * volume
        net_cash = gross_cash - commission_cash + swap_cash
        net_r = net_cash / risk_cash if risk_cash > 0 else None
    else:
        gross_cash = risk_cash = net_cash = None
        net_r = gross_r_price if commission_cash == 0 and swap_cash == 0 else None

    return {
        "status": "closed", "symbol": symbol, "side": side, "volume": volume,
        "signal_time_utc": _utc_label(int(bars[signal_index]["time"])),
        "entry_time_utc": _utc_label(entry_epoch), "exit_time_utc": _utc_label(exit_epoch),
        "entry_price": entry, "exit_price": exit_price, "stop": stop, "target": target,
        "exit_reason": exit_reason, "same_bar_ambiguous": same_bar_ambiguous,
        "gross_r_price": gross_r_price, "net_r": net_r,
        "gross_cash_estimate": gross_cash, "net_cash_estimate": net_cash,
        "risk_cash_estimate": risk_cash, "commission_cash_assumption": commission_cash,
        "swap_cash_assumption": swap_cash, "utc_date_rollovers_estimated": rollovers,
        "exit_index": exit_index,
    }


def run_pullback_replay(*, symbol: str, timeframe: str, bars: list[dict[str, Any]],
                        contract: dict[str, Any], slippage_points: float = 1.0,
                        commission_per_lot_round_turn: float = 0.0,
                        swap_long_per_lot_per_utc_rollover: float = 0.0,
                        swap_short_per_lot_per_utc_rollover: float = 0.0,
                        costs_confirmed: bool = False,
                        evaluation_start_index: int = 59,
                        signal_rule: str = "pullback_sma21") -> dict[str, Any]:
    """Run the live pullback rule causally over closed MT5 OHLC bars; never sends orders."""
    symbol = str(symbol).strip()
    timeframe = str(timeframe).upper()
    if not MT5_SYMBOL_PATTERN.fullmatch(symbol):
        raise ReplayValidationError("Ativo inválido.")
    if timeframe not in TIMEFRAMES_SECONDS:
        raise ReplayValidationError("Timeframe MT5 não suportado.")
    if signal_rule not in {"pullback_sma21", "momentum20_zero_cross"}:
        raise ReplayValidationError("Regra de replay não suportada.")
    if not costs_confirmed:
        raise ReplayValidationError("Confirme que os parâmetros de custo representam sua conta MT5.")
    if (not isinstance(bars, list) or len(bars) < 61 or len(bars) > MAX_REPLAY_BARS
            or any(not isinstance(row, dict) for row in bars)):
        raise ReplayValidationError(f"O replay exige de 61 a {MAX_REPLAY_BARS} candles fechados.")
    if (not isinstance(evaluation_start_index, int) or isinstance(evaluation_start_index, bool)
            or evaluation_start_index < 59 or evaluation_start_index >= len(bars) - 1):
        raise ReplayValidationError("O início do segmento de avaliação está fora do histórico.")

    slippage_points = _finite(slippage_points, "slippage_points", minimum=0,
                              maximum=MAX_SLIPPAGE_POINTS)
    commission = _finite(commission_per_lot_round_turn, "commission_per_lot_round_turn",
                         minimum=0, maximum=MAX_CASH_COST_PER_LOT)
    swap_long = _finite(swap_long_per_lot_per_utc_rollover,
                        "swap_long_per_lot_per_utc_rollover",
                        minimum=-MAX_CASH_COST_PER_LOT, maximum=MAX_CASH_COST_PER_LOT)
    swap_short = _finite(swap_short_per_lot_per_utc_rollover,
                         "swap_short_per_lot_per_utc_rollover",
                         minimum=-MAX_CASH_COST_PER_LOT, maximum=MAX_CASH_COST_PER_LOT)
    point = _finite(contract.get("point"), "point", minimum=1e-12)
    tick_size = _finite(contract.get("trade_tick_size") or point, "trade_tick_size", minimum=1e-12)
    volume_min = _finite(contract.get("volume_min"), "volume_min", minimum=1e-8)
    volume_step = _finite(contract.get("volume_step"), "volume_step", minimum=1e-8)
    if int(contract.get("chart_mode", 0)) != 0:
        raise ReplayValidationError("O gráfico do ativo não está em preços Bid; o replay OHLC não consegue reconstruir Bid/Ask com segurança.")
    if volume_min > 0.01 or volume_step > 0.01:
        raise ReplayValidationError("O volume mínimo/passo do ativo excede o limite atual de 0,01 lote.")

    try:
        ordered_bars = sorted(bars, key=lambda row: int(row["time"]))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ReplayValidationError("O histórico contém horário de candle inválido.") from exc
    clean: list[dict[str, Any]] = []
    missing_spreads = 0
    for raw in ordered_bars:
        if not isinstance(raw, dict) or any(key not in raw for key in ("time", "open", "high", "low", "close")):
            raise ReplayValidationError("O histórico contém candles sem campos OHLC completos.")
        timestamp = int(raw["time"])
        values = {key: _finite(raw[key], key, minimum=1e-12)
                  for key in ("open", "high", "low", "close")}
        if values["high"] < max(values["open"], values["close"], values["low"]):
            raise ReplayValidationError("O histórico contém candle OHLC inconsistente.")
        if values["low"] > min(values["open"], values["close"], values["high"]):
            raise ReplayValidationError("O histórico contém candle OHLC inconsistente.")
        if clean and timestamp <= clean[-1]["time"]:
            raise ReplayValidationError("O histórico contém timestamps duplicados.")
        raw_spread = raw.get("spread")
        try:
            spread_points = _finite(raw_spread, "spread", minimum=0) if raw_spread is not None else None
        except ReplayValidationError:
            spread_points = None
        missing_spreads += int(spread_points is None)
        clean.append({**raw, **values, "time": timestamp, "spread": spread_points})

    volume = round(volume_min, 8)
    if volume < volume_min or volume <= 0:
        raise ReplayValidationError("Não existe lote compatível com o teto de 0,01 lote para este ativo.")

    version = (REPLAY_VERSION if signal_rule == "pullback_sma21"
               else "momentum20-zero-cross-ohlc-v1")
    params = {"version": version, "signal_rule": signal_rule,
              "evaluation_start_index": evaluation_start_index,
              "symbol": symbol, "timeframe": timeframe,
              "bars": len(clean), "volume": volume, "slippage_points_per_side": slippage_points,
              "commission_per_lot_round_turn": commission,
              "swap_long_per_lot_per_utc_rollover": swap_long,
              "swap_short_per_lot_per_utc_rollover": swap_short,
              "costs_confirmed": True, "same_bar_policy": "stop_first"}
    data_sha256 = hashlib.sha256(json.dumps(
        {"bars": clean, "contract": contract, "parameters": params},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")).hexdigest()

    trades: list[dict[str, Any]] = []
    eligible_signals = 0
    skipped_entries: dict[str, int] = {}
    same_bar_ambiguous = 0
    censored = 0
    non_signal_bars = 0
    eligible_limit_reached = False
    last_exit_index = 0
    timeframe_seconds = TIMEFRAMES_SECONDS[timeframe]
    for index in range(evaluation_start_index, len(clean) - 1):
        if index <= last_exit_index:
            continue
        current = clean[index]
        spread_price = current["spread"] * point if current["spread"] is not None else None
        tick = ({"bid": current["close"], "ask": current["close"] + spread_price}
                if spread_price is not None else None)
        if signal_rule == "pullback_sma21":
            analysis = analyze_market(
                symbol, timeframe, clean[:index + 1], contract,
                tick,
                now_epoch=current["time"] + timeframe_seconds,
            )
        else:
            analysis = _momentum_baseline_decision(clean[:index + 1], contract, point)
        decision = analysis.get("decision", {})
        if not decision.get("order_eligible"):
            non_signal_bars += 1
            continue
        eligible_signals += 1
        if len(trades) >= MAX_REPLAY_TRADES:
            eligible_limit_reached = True
            break
        simulated = _simulate_trade(
            bars=clean, signal_index=index, symbol=symbol, side=decision["side"],
            stop=float(decision["stop"]), target=float(decision["target"]),
            contract={**contract, "point": point, "trade_tick_size": tick_size},
            slippage_points=slippage_points,
            commission_per_lot_round_turn=commission,
            swap_long_per_lot_per_utc_rollover=swap_long,
            swap_short_per_lot_per_utc_rollover=swap_short,
            volume=volume,
        )
        if simulated["status"] == "skipped":
            reason = simulated["reason"]
            skipped_entries[reason] = skipped_entries.get(reason, 0) + 1
            continue
        if simulated["status"] == "censored":
            censored += 1
            trades.append(simulated)
            last_exit_index = len(clean) - 1
            continue
        same_bar_ambiguous += int(simulated["same_bar_ambiguous"])
        last_exit_index = int(simulated.pop("exit_index"))
        trades.append(simulated)

    closed = [trade for trade in trades if trade["status"] == "closed"]
    known_net_r = [float(trade["net_r"]) for trade in closed if trade.get("net_r") is not None]
    known_cash = [float(trade["net_cash_estimate"]) for trade in closed
                  if trade.get("net_cash_estimate") is not None]
    wins = sum(value > 0 for value in known_net_r)
    losses_r = sum(value for value in known_net_r if value < 0)
    gains_r = sum(value for value in known_net_r if value > 0)
    equity_curve: list[float] = []
    equity = peak = max_drawdown_r = 0.0
    for value in known_net_r:
        equity += value
        peak = max(peak, equity)
        max_drawdown_r = max(max_drawdown_r, peak - equity)
        equity_curve.append(equity)

    spread_missing = missing_spreads
    spread_zero = sum(1 for bar in clean if bar.get("spread") == 0)
    overnight_closed = sum(1 for trade in closed if trade["utc_date_rollovers_estimated"] > 0)
    net_r_sum = sum(known_net_r) if known_net_r else None
    result = {
        "version": version, "status": "triagem_ohlc_nao_homologado",
        "symbol": symbol, "timeframe": timeframe, "bars_used": len(clean),
        "first_bar_utc": _utc_label(int(clean[0]["time"])),
        "last_bar_utc": _utc_label(int(clean[-1]["time"])), "data_sha256": data_sha256,
        "parameters": params,
        "metrics": {
            "closed_trades": len(closed), "censored_positions": censored,
            "eligible_signals": eligible_signals, "bars_without_eligible_signal": non_signal_bars,
            "skipped_after_gap": sum(skipped_entries.values()), "skipped_reasons": skipped_entries,
            "same_bar_stop_first_cases": same_bar_ambiguous,
            "win_rate_pct": (wins / len(known_net_r) * 100) if known_net_r else None,
            "net_r_total": net_r_sum,
            "expectancy_r": (net_r_sum / len(known_net_r)) if known_net_r else None,
            "max_drawdown_r": max_drawdown_r if known_net_r else None,
            "profit_factor_r": (gains_r / abs(losses_r)) if losses_r else None,
            "net_cash_estimate": sum(known_cash) if known_cash else None,
            "trades_with_cost_cash": len(known_cash),
            "overnight_trades": overnight_closed,
            "trade_cap_reached": eligible_limit_reached,
            "volume_simulated": volume,
        },
        "data_quality": {
            "spread_missing_bars": spread_missing, "zero_spread_bars": spread_zero,
            "spread_source": "spread por candle retornado pelo MT5; aproximado e não intrabar",
        "cash_conversion": "valor de tick atual do contrato do broker; não reproduz conversões históricas",
        "swap_method": "valor informado pelo usuário por virada de data UTC; não reproduz fuso/rolagem tripla do broker",
        "chart_mode": int(contract.get("chart_mode", 0)),
        },
        "limitations": [
            "Replay em OHLC fechado; não usa sequência de ticks reais nem o Strategy Tester do MT5.",
            "Quando stop e alvo cabem no mesmo candle, o stop é considerado primeiro.",
            "Entrada é estimada na abertura do candle seguinte, com spread histórico por candle e slippage informado.",
            "Os timestamps de barras são usados em UTC conforme a API Python do MT5; o offset do tick atual não é aplicado ao histórico.",
            "Comissão e swap são premissas informadas pelo usuário; confirme a tabela da corretora.",
            "Conversão monetária usa valores de tick atuais; os resultados não comprovam vantagem nem homologação.",
            "Posições não encerradas dentro da amostra são censuradas e ficam fora das métricas de trades fechados.",
        ],
        "trades": trades[:200],
    }
    return result


def run_pullback_validation(*, symbol: str, timeframe: str,
                            bars: list[dict[str, Any]], contract: dict[str, Any],
                            slippage_points: float = 1.0,
                            commission_per_lot_round_turn: float = 0.0,
                            swap_long_per_lot_per_utc_rollover: float = 0.0,
                            swap_short_per_lot_per_utc_rollover: float = 0.0,
                            costs_confirmed: bool = False) -> dict[str, Any]:
    """Compare the fixed pullback rule with a simple momentum baseline chronologically.

    The first 70% is a historical development/context segment. The final 30% is
    a holdout and receives no entries from the earlier segment. No parameters are
    fitted or selected by this function.
    """
    if not isinstance(bars, list) or len(bars) < MIN_VALIDATION_BARS:
        raise ReplayValidationError(
            f"A validação cronológica exige pelo menos {MIN_VALIDATION_BARS} candles do broker.")
    if len(bars) > MAX_REPLAY_BARS:
        raise ReplayValidationError(f"O replay aceita no máximo {MAX_REPLAY_BARS} candles.")
    try:
        ordered_bars = sorted(bars, key=lambda row: int(row["time"]))
        timestamps = [int(row["time"]) for row in ordered_bars]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise ReplayValidationError("O histórico contém horários de candle inválidos.") from exc
    if any(right <= left for left, right in zip(timestamps[:-1], timestamps[1:], strict=True)):
        raise ReplayValidationError("O histórico contém timestamps duplicados.")

    split_index = int(len(ordered_bars) * DEVELOPMENT_FRACTION)
    development_bars = ordered_bars[:split_index]
    if len(development_bars) < 61 or len(ordered_bars) - split_index < 60:
        raise ReplayValidationError("A divisão precisa preservar contexto e pelo menos 60 candles no holdout.")

    common = {
        "symbol": symbol, "timeframe": timeframe, "contract": contract,
        "slippage_points": slippage_points,
        "commission_per_lot_round_turn": commission_per_lot_round_turn,
        "swap_long_per_lot_per_utc_rollover": swap_long_per_lot_per_utc_rollover,
        "swap_short_per_lot_per_utc_rollover": swap_short_per_lot_per_utc_rollover,
        "costs_confirmed": costs_confirmed,
    }
    development = {
        "pullback": run_pullback_replay(
            **{**common, "bars": development_bars, "signal_rule": "pullback_sma21"}),
        "baseline": run_pullback_replay(
            **{**common, "bars": development_bars,
               "signal_rule": "momentum20_zero_cross"}),
        "start_utc": _utc_label(timestamps[0]),
        "end_utc": _utc_label(timestamps[split_index - 1]),
        "bars": split_index,
        "purpose": "contexto_de_desenvolvimento_sem_ajuste_automatico",
    }
    holdout = {
        "pullback": run_pullback_replay(
            **{**common, "bars": ordered_bars,
               "evaluation_start_index": split_index,
               "signal_rule": "pullback_sma21"}),
        "baseline": run_pullback_replay(
            **{**common, "bars": ordered_bars,
               "evaluation_start_index": split_index,
               "signal_rule": "momentum20_zero_cross"}),
        "start_utc": _utc_label(timestamps[split_index]),
        "end_utc": _utc_label(timestamps[-1]),
        "bars": len(ordered_bars) - split_index,
        "purpose": "holdout_cronologico_nao_usado_para_escolher_parametros",
    }
    parameters = {
        "validation_version": "chronological-holdout-pullback-v1",
        "symbol": str(symbol).strip(),
        "timeframe": str(timeframe).upper(),
        "development_fraction": DEVELOPMENT_FRACTION,
        "development_bars": split_index,
        "holdout_bars": len(ordered_bars) - split_index,
        "holdout_start_index": split_index,
        "pullback_rule": "pullback_sma21",
        "baseline_rule": "momentum20_zero_cross",
        "baseline_risk_management": "ATR14 stop 1.0x; target 1.5R; same OHLC cost model",
        "slippage_points_per_side": _finite(slippage_points, "slippage_points", minimum=0,
                                              maximum=MAX_SLIPPAGE_POINTS),
        "commission_per_lot_round_turn": _finite(
            commission_per_lot_round_turn, "commission_per_lot_round_turn", minimum=0,
            maximum=MAX_CASH_COST_PER_LOT),
        "swap_long_per_lot_per_utc_rollover": _finite(
            swap_long_per_lot_per_utc_rollover, "swap_long_per_lot_per_utc_rollover",
            minimum=-MAX_CASH_COST_PER_LOT, maximum=MAX_CASH_COST_PER_LOT),
        "swap_short_per_lot_per_utc_rollover": _finite(
            swap_short_per_lot_per_utc_rollover, "swap_short_per_lot_per_utc_rollover",
            minimum=-MAX_CASH_COST_PER_LOT, maximum=MAX_CASH_COST_PER_LOT),
        "costs_confirmed": costs_confirmed,
        "trade_management_shared": True,
    }
    data_sha256 = hashlib.sha256(json.dumps(
        {"bars": ordered_bars, "contract": contract, "parameters": parameters},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    ).encode("utf-8")).hexdigest()

    pullback_metrics = holdout["pullback"]["metrics"]
    baseline_metrics = holdout["baseline"]["metrics"]
    pullback_trades = pullback_metrics["closed_trades"]
    baseline_trades = baseline_metrics["closed_trades"]
    adequate_sample = (pullback_trades >= MIN_HOLDOUT_TRADES_FOR_REVIEW
                       and baseline_trades >= MIN_HOLDOUT_TRADES_FOR_REVIEW)
    pullback_r = pullback_metrics.get("net_r_total")
    baseline_r = baseline_metrics.get("net_r_total")
    delta_r = (pullback_r - baseline_r
               if pullback_r is not None and baseline_r is not None else None)
    comparison = {
        "baseline_label": "Momentum de 20 candles: cruzamento do retorno para além de zero",
        "shared_exit_and_cost_assumptions": True,
        "holdout_pullback_net_r": pullback_r,
        "holdout_baseline_net_r": baseline_r,
        "holdout_delta_net_r": delta_r,
        "pullback_closed_trades": pullback_trades,
        "baseline_closed_trades": baseline_trades,
        "minimum_trades_for_descriptive_review": MIN_HOLDOUT_TRADES_FOR_REVIEW,
        "sample_status": ("amostra_descritiva_minima_atingida" if adequate_sample
                          else "amostra_insuficiente_sem_conclusao"),
        "interpretation": (
            "Diferença apenas descritiva; ainda requer dados por tick, custos históricos e outra janela intocada."
            if adequate_sample else
            "A amostra de trades no holdout é pequena; não concluir superioridade nem ausência de vantagem."
        ),
    }
    limitations = list(dict.fromkeys(
        development["pullback"]["limitations"]
        + [
            "O baseline é um cruzamento de retorno de 20 candles e usa o mesmo stop ATR14, alvo 1,5R e custos assumidos.",
            "O primeiro segmento é contexto de desenvolvimento, não treino de modelo; os parâmetros permanecem fixos.",
            "O holdout deve permanecer intocado; qualquer ajuste após inspecioná-lo exige uma nova janela futura.",
            "Uma comparação OHLC não substitui teste do Strategy Tester Every tick based on real ticks.",
        ]
    ))
    return {
        "version": "chronological-holdout-pullback-v1",
        "status": "triagem_ohlc_holdout_nao_homologado",
        "symbol": symbol,
        "timeframe": timeframe,
        "bars_used": len(ordered_bars),
        "first_bar_utc": _utc_label(timestamps[0]),
        "last_bar_utc": _utc_label(timestamps[-1]),
        "data_sha256": data_sha256,
        "parameters": parameters,
        "metrics": pullback_metrics,
        "trades": holdout["pullback"]["trades"],
        "segments": {"development": development, "holdout": holdout},
        "comparison": comparison,
        "data_quality": {
            "history_source": "candles OHLC fechados do histórico do broker via MetaTrader 5 Python API",
            "timestamp_basis": "UTC informado pela API Python oficial do MetaTrader 5",
            "history_coverage": {"bars": len(ordered_bars), "first_utc": _utc_label(timestamps[0]),
                                 "last_utc": _utc_label(timestamps[-1])},
            "dataset_sha256_includes": ["candles completos", "contrato do ativo", "parâmetros da divisão"],
        },
        "limitations": limitations,
    }
