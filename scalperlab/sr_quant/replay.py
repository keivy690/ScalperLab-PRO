"""Offline OHLC triage for the exact S/R research evaluator."""
from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from ..config import MT5_SYMBOL_PATTERN
from ..replay import ReplayValidationError, _finite, _momentum_baseline_decision, _simulate_trade
from .core import FRAMES, MIN_BARS, RULE_VERSION, evaluate_bundle

FAMILIES = ("trend_pullback", "breakout_retest", "range_fakeout")
FRAME_SECONDS = {"H1": 3600, "M15": 900, "M5": 300}
MAX_M5_BARS = 2500
MIN_M5_BARS = 600


def _metrics(trades: list[dict[str, Any]], signals: int) -> dict[str, Any]:
    closed = [row for row in trades if row.get("status") == "closed"]
    returns = [float(row["net_r"]) for row in closed if row.get("net_r") is not None]
    equity = peak = drawdown = 0.0
    for value in returns:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    gains = sum(value for value in returns if value > 0)
    losses = sum(value for value in returns if value < 0)
    return {"signals": signals, "closed_trades": len(closed),
            "censored": sum(row.get("status") == "censored" for row in trades),
            "skipped": sum(row.get("status") == "skipped" for row in trades),
            "same_bar_stop_first": sum(bool(row.get("same_bar_ambiguous")) for row in closed),
            "known_net_r_trades": len(returns),
            "net_r": sum(returns) if returns else None,
            "expectancy_r": sum(returns) / len(returns) if returns else None,
            "win_rate_pct": 100 * sum(value > 0 for value in returns) / len(returns) if returns else None,
            "max_drawdown_r": drawdown if returns else None,
            "profit_factor_r": gains / abs(losses) if losses else None,
            "sample_status": "amostra_insuficiente" if len(closed) < 30 else "revisao_necessaria"}


def _validate_rows(rows: Any, frame: str) -> list[dict[str, Any]]:
    if not isinstance(rows, list) or len(rows) < MIN_BARS[frame]:
        raise ReplayValidationError(f"Histórico {frame} insuficiente para S/R.")
    cleaned = []
    for raw in rows:
        if not isinstance(raw, dict):
            raise ReplayValidationError(f"Candle {frame} inválido.")
        try:
            stamp = int(raw["time"])
            values = {name: _finite(raw[name], name, minimum=1e-12)
                      for name in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ReplayValidationError(f"Candle {frame} incompleto ou inválido.") from exc
        if (cleaned and stamp <= cleaned[-1]["time"]
                or values["high"] < max(values.values())
                or values["low"] > min(values.values())):
            raise ReplayValidationError(f"Sequência ou OHLC {frame} inconsistente.")
        spread = raw.get("spread")
        spread_points = (_finite(spread, "spread", minimum=0)
                         if spread is not None else None)
        cleaned.append({**raw, **values, "time": stamp, "spread": spread_points})
    return cleaned


def run_sr_replay(*, symbol: str, frames: dict[str, list[dict[str, Any]]],
                  contract: dict[str, Any], slippage_points: float,
                  commission_per_lot_round_turn: float,
                  swap_long_per_lot_per_utc_rollover: float,
                  swap_short_per_lot_per_utc_rollover: float,
                  costs_confirmed: bool) -> dict[str, Any]:
    """Replay the same causal evaluator with broker OHLC and conservative fills.

    The caller must first verify the UTC basis of all three histories. This
    function cannot infer a historical server offset or validate profitability.
    """
    if not MT5_SYMBOL_PATTERN.fullmatch(str(symbol)):
        raise ReplayValidationError("Ativo inválido.")
    if costs_confirmed is not True:
        raise ReplayValidationError("Confirme os custos de execução do broker.")
    if not isinstance(frames, dict):
        raise ReplayValidationError("Informe os três históricos H1, M15 e M5.")
    clean = {frame: _validate_rows(frames.get(frame), frame) for frame in FRAMES}
    m5 = clean["M5"]
    if not MIN_M5_BARS <= len(m5) <= MAX_M5_BARS:
        raise ReplayValidationError(f"Use entre {MIN_M5_BARS} e {MAX_M5_BARS} candles M5 fechados.")
    if int(contract.get("chart_mode", 0)) != 0:
        raise ReplayValidationError("O gráfico não é Bid; a aproximação Bid/Ask seria inválida.")
    point = _finite(contract.get("point"), "point", minimum=1e-12)
    volume = _finite(contract.get("volume_min"), "volume_min", minimum=1e-8)
    step = _finite(contract.get("volume_step"), "volume_step", minimum=1e-8)
    if volume > 0.01 or step > 0.01:
        raise ReplayValidationError("Lote mínimo/passo excede o limite de 0,01 do replay.")
    slippage = _finite(slippage_points, "slippage_points", minimum=0, maximum=100)
    commission = _finite(commission_per_lot_round_turn, "commission", minimum=0, maximum=10000)
    swap_long = _finite(swap_long_per_lot_per_utc_rollover, "swap_long", minimum=-10000, maximum=10000)
    swap_short = _finite(swap_short_per_lot_per_utc_rollover, "swap_short", minimum=-10000, maximum=10000)
    params = {"version": RULE_VERSION, "symbol": symbol, "timeframe": "M5",
              "slippage_points_per_side": slippage,
              "commission_per_lot_round_turn": commission,
              "swap_long_per_lot_per_utc_rollover": swap_long,
              "swap_short_per_lot_per_utc_rollover": swap_short,
              "costs_confirmed": True, "volume": volume, "same_bar_policy": "stop_first"}
    digest = hashlib.sha256(json.dumps(
        {"frames": clean, "contract": contract, "parameters": params},
        sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    closed_times = {frame: [int(row["time"]) + FRAME_SECONDS[frame] for row in rows]
                    for frame, rows in clean.items()}
    split = int(len(m5) * 0.70)
    segments: dict[str, Any] = {}
    for name, start, end in (("development", 0, split), ("holdout", split, len(m5))):
        ledger = {family: [] for family in (*FAMILIES, "momentum20_baseline")}
        signals = Counter()
        filters = Counter()
        last_exit = {family: -1 for family in ledger}
        outcomes = m5[:end]
        evaluated = 0
        for index in range(start, end - 1):
            decision_time = int(m5[index]["time"]) + 300
            slices = {}
            for frame in FRAMES:
                cutoff = bisect_right(closed_times[frame], decision_time)
                window = 260 if frame in {"H1", "M15"} else 300
                slices[frame] = clean[frame][max(0, cutoff - window):cutoff]
            if any(len(slices[frame]) < MIN_BARS[frame] for frame in FRAMES):
                filters["insufficient_history"] += 1
                continue
            spread = m5[index].get("spread")
            tick = ({"bid": m5[index]["close"],
                     "ask": m5[index]["close"] + spread * point}
                    if spread is not None else {})
            decision = evaluate_bundle(
                {"symbol": symbol, "frames": slices, "contract": contract, "tick": tick},
                decision_time=decision_time)
            evaluated += 1
            filters.update(decision.get("filter_counts") or {})
            proposals = list(decision.get("candidates") or [])
            baseline = _momentum_baseline_decision(slices["M5"], contract, point)
            baseline_signal = baseline.get("decision", {})
            if baseline_signal.get("order_eligible"):
                proposals.append({**baseline_signal, "strategy": "momentum20_baseline",
                                  "status": "CANDIDATE_RESEARCH_ONLY"})
            for candidate in proposals:
                family = candidate["strategy"]
                signals[family] += 1
                if candidate.get("status") != "CANDIDATE_RESEARCH_ONLY":
                    filters[f"{family}_blocked_{candidate.get('status')}"] += 1
                    continue
                if index <= last_exit[family]:
                    filters[f"{family}_position_open"] += 1
                    continue
                if len(ledger[family]) >= 500:
                    filters[f"{family}_trade_cap"] += 1
                    continue
                trade = _simulate_trade(
                    bars=outcomes, signal_index=index, symbol=symbol,
                    side=candidate["side"], stop=float(candidate["stop"]),
                    target=float(candidate["target"]), contract=contract,
                    slippage_points=slippage,
                    commission_per_lot_round_turn=commission,
                    swap_long_per_lot_per_utc_rollover=swap_long,
                    swap_short_per_lot_per_utc_rollover=swap_short,
                    volume=volume)
                if trade["status"] == "closed":
                    last_exit[family] = int(trade.pop("exit_index"))
                elif trade["status"] == "censored":
                    last_exit[family] = len(outcomes) - 1
                ledger[family].append(trade)
        segments[name] = {
            "first_bar_utc": datetime.fromtimestamp(m5[start]["time"], UTC).isoformat(),
            "last_bar_utc": datetime.fromtimestamp(m5[end - 1]["time"], UTC).isoformat(),
            "bars": end - start, "evaluated_bars": evaluated,
            "filters": dict(filters),
            "families": {family: _metrics(ledger[family], signals[family]) for family in ledger},
            "trades": {family: ledger[family][:100] for family in ledger},
        }
    baseline_r = segments["holdout"]["families"]["momentum20_baseline"]["net_r"]
    comparison = {}
    for family in FAMILIES:
        family_r = segments["holdout"]["families"][family]["net_r"]
        comparison[family] = {
            "holdout_delta_net_r_vs_baseline": (
                family_r - baseline_r if family_r is not None and baseline_r is not None else None),
            "sample_status": segments["holdout"]["families"][family]["sample_status"],
        }
    return {"version": RULE_VERSION, "symbol": symbol,
            "status": "triagem_ohlc_nao_homologado", "mode": "research_only",
            "order_eligible": False, "data_sha256": digest,
            "parameters": params, "segments": segments, "comparison": comparison,
            "data_quality": {"spread_missing_m5": sum(row.get("spread") is None for row in m5),
                             "spread_zero_m5": sum(row.get("spread") == 0 for row in m5)},
            "limitations": [
                "Histórico H1/M15/M5 deve ter base UTC confirmada antes deste replay.",
                "Candles OHLC não informam a sequência intrabar; stop é considerado primeiro.",
                "Spread por candle e slippage informado aproximam execução; não são ticks reais.",
                "Comissão, swap e valor de tick são premissas; conversão histórica pode diferir.",
                "Cada família é simulada isoladamente; sinais concorrentes não são carteira combinada.",
                "Menos de 30 operações fechadas no holdout é amostra insuficiente, não aprovação.",
            ]}
