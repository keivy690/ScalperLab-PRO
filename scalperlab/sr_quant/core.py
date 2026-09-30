from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

from ..mt5_time import MT5_TIMEFRAME_SECONDS
from ..trading.ports import TradingPort
from .time_archive import examine_sample

RULE_VERSION = "sr-quant-research-v1"
FRAMES = ("H1", "M15", "M5")
FRAME_COUNTS = {"H1": 260, "M15": 260, "M5": 300}
MIN_BARS = {"H1": 215, "M15": 60, "M5": 30}
MAX_SPREAD_ATR_M5 = 0.08  # Research hypothesis; not a universal broker limit.


def read_live_broker_bundle(port: TradingPort, symbol: str) -> dict[str, Any]:
    """Anchor raw broker-time H1/M15/M5 to a verified current M1/tick.

    Historical bars stay in the broker's time domain for causal indicators. This
    does not assert an unproved historical UTC offset and cannot feed replay.
    """
    started = time.monotonic()
    sample = port.sr_raw_time_sample(symbol, max(FRAME_COUNTS.values()))
    if not sample.get("ok") or sample.get("symbol") != symbol:
        return {"ok": False, "symbol": symbol,
                "code": sample.get("code") or "raw_sample_unavailable",
                "detail": sample.get("detail") or "Leitura bruta MT5 indisponível."}
    anchor = examine_sample(sample)
    if not anchor.get("ok"):
        return {"ok": False, "symbol": symbol,
                "code": anchor.get("code") or "broker_time_unverified",
                "detail": "Candle atual e tick UTC não confirmaram a mesma base temporal."}
    account = sample.get("account") or {}
    if not account.get("login") or not account.get("server"):
        return {"ok": False, "symbol": symbol, "code": "account_unavailable",
                "detail": "Identidade da conta MT5 indisponível."}
    frames = {frame: list(sample["frames"][frame]["closed"][-FRAME_COUNTS[frame]:])
              for frame in FRAMES}
    if any(not frames[frame] for frame in FRAMES):
        return {"ok": False, "symbol": symbol, "code": "history_unavailable",
                "detail": "Histórico H1/M15/M5 indisponível."}
    offset = int(anchor["bar_offset_seconds"])
    return {"ok": True, "symbol": symbol, "frames": frames,
            "contract": sample.get("contract") or {}, "tick": sample["tick"],
            "account": account, "terminal_id": sample.get("terminal_id"),
            "raw_sample": sample, "decision_time_raw": int(sample["tick"]["time"]) + offset,
            "bar_offset_seconds": offset,
            "time_normalization": {"basis": "broker_raw_for_causal_indicators",
                                   "historical_timezone_verified": False,
                                   "current_m1_anchor_verified": True,
                                   "current_bar_offset_seconds": offset,
                                   "sample_sha256": anchor["sample_sha256"]},
            "connector_diagnostics": {"calls": 1,
                                      "elapsed_seconds": round(time.monotonic() - started, 3)}}


def evaluate_live_broker_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    """Convert only recent decision timestamps back to UTC for audit/deduping."""
    offset = int(bundle["bar_offset_seconds"])
    result = evaluate_bundle(bundle, decision_time=int(bundle["decision_time_raw"]))
    result["decision_time_utc"] = int(bundle["tick"]["time"])
    result["frame_last_closed"] = {
        frame: (raw - offset if raw is not None else None)
        for frame, raw in result["frame_last_closed"].items()}
    for candidate in result.get("candidates", []):
        candidate["signal_bar_open_utc"] -= offset
    result["time_basis"] = "broker_raw_history_current_utc_anchor"
    result["historical_timezone_verified"] = False
    result["bar_offset_applied_to_recent_signal_seconds"] = offset
    return result


def read_live_bundle(port: TradingPort, symbol: str, *,
                     frame_cache: dict[tuple[str, str], dict[str, Any]] | None = None) -> dict[str, Any]:
    """Read-only frame bundle from the existing connector; never arms an engine."""
    started = time.monotonic()
    calls = 0
    cached = 0
    frames: dict[str, list[dict[str, Any]]] = {}
    normalization: dict[str, dict[str, Any]] = {}
    contract: dict[str, Any] | None = None
    for timeframe in FRAMES:
        cache_key = (symbol, timeframe)
        stored = frame_cache.get(cache_key) if frame_cache is not None else None
        stored_bars = stored.get("bars") if isinstance(stored, dict) else None
        next_close = (int(stored_bars[-1]["time"]) + 2 * MT5_TIMEFRAME_SECONDS[timeframe]
                      if stored_bars else 0)
        if timeframe in {"H1", "M15"} and stored and time.time() < next_close:
            result = stored
            cached += 1
        else:
            result = port.strategy_market_data(symbol, FRAME_COUNTS[timeframe], timeframe)
            calls += 1
        if not result.get("ok"):
            return {"ok": False, "symbol": symbol, "timeframe": timeframe,
                    "code": result.get("code") or "frame_unavailable",
                    "detail": result.get("detail") or "Histórico MT5 indisponível."}
        if result.get("symbol") != symbol:
            return {"ok": False, "symbol": symbol, "timeframe": timeframe,
                    "code": "symbol_mismatch",
                    "detail": "O conector retornou outro símbolo; leitura cancelada."}
        temporal = result.get("time_normalization") or {}
        if temporal.get("basis") != "UTC" or (
                timeframe in {"H1", "M15"}
                and temporal.get("historical_timezone_verified") is not True):
            return {"ok": False, "symbol": symbol, "timeframe": timeframe,
                    "code": "historical_utc_unverified",
                    "detail": "Base histórica UTC do timeframe não confirmada; pesquisa S/R suspensa."}
        if contract is None or timeframe == "M5":
            contract = result.get("contract") or {}
        frames[timeframe] = result.get("bars") or []
        normalization[timeframe] = temporal
        if frame_cache is not None and result is not stored:
            frame_cache[cache_key] = result
    tick = port.current_tick(symbol)
    calls += 1
    if not tick.get("ok"):
        return {"ok": False, "symbol": symbol,
                "code": tick.get("code") or "tick_unavailable",
                "detail": tick.get("detail") or "Cotação indisponível."}
    return {"ok": True, "symbol": symbol, "frames": frames,
            "time_normalization": normalization, "contract": contract or {}, "tick": tick,
            "connector_diagnostics": {"calls": calls, "frames_cached": cached,
                                      "elapsed_seconds": round(time.monotonic() - started, 3)}}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _closed_bars(rows: Any, timeframe: str, decision_time: int) -> list[dict[str, Any]]:
    if not isinstance(rows, list):
        return []
    seconds = MT5_TIMEFRAME_SECONDS[timeframe]
    closed: list[dict[str, Any]] = []
    previous_time = -1
    for row in rows:
        if not isinstance(row, dict):
            return []
        try:
            stamp = int(row["time"])
        except (KeyError, TypeError, ValueError, OverflowError):
            return []
        if stamp <= previous_time:
            return []
        previous_time = stamp
        if stamp + seconds > decision_time:
            continue
        prices = [_finite(row.get(key)) for key in ("open", "high", "low", "close")]
        if (any(value is None or value <= 0 for value in prices)
                or prices[1] < max(prices[0], prices[2], prices[3])
                or prices[2] > min(prices[0], prices[1], prices[3])):
            return []
        closed.append(row)
    return closed


def _ema(values: list[float], period: int) -> float | None:
    if len(values) < period:
        return None
    value = sum(values[:period]) / period
    alpha = 2.0 / (period + 1)
    for close in values[period:]:
        value += alpha * (close - value)
    return value


def _atr(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) <= period:
        return None
    ranges = []
    for previous, current in zip(bars[:-1], bars[1:], strict=True):
        ranges.append(max(current["high"] - current["low"],
                          abs(current["high"] - previous["close"]),
                          abs(current["low"] - previous["close"])))
    return sum(ranges[-period:]) / period


def _adx(bars: list[dict[str, Any]], period: int = 14) -> float | None:
    if len(bars) < period * 3:
        return None
    plus_dm, minus_dm, true_ranges = [], [], []
    for previous, current in zip(bars[:-1], bars[1:], strict=True):
        up = current["high"] - previous["high"]
        down = previous["low"] - current["low"]
        plus_dm.append(up if up > down and up > 0 else 0.0)
        minus_dm.append(down if down > up and down > 0 else 0.0)
        true_ranges.append(max(current["high"] - current["low"],
                               abs(current["high"] - previous["close"]),
                               abs(current["low"] - previous["close"])))
    dx: list[float] = []
    for end in range(period, len(true_ranges) + 1):
        tr = sum(true_ranges[end - period:end])
        if tr <= 0:
            dx.append(0.0)
            continue
        plus = sum(plus_dm[end - period:end]) / tr
        minus = sum(minus_dm[end - period:end]) / tr
        dx.append(100.0 * abs(plus - minus) / (plus + minus) if plus + minus else 0.0)
    return sum(dx[-period:]) / period if len(dx) >= period else None


def _regime(h1: list[dict[str, Any]], m15: list[dict[str, Any]]) -> dict[str, Any]:
    h1_closes = [row["close"] for row in h1]
    m15_closes = [row["close"] for row in m15]
    e20, e50, e200 = (_ema(h1_closes, period) for period in (20, 50, 200))
    m20, m50 = _ema(m15_closes, 20), _ema(m15_closes, 50)
    adx, atr = _adx(h1), _atr(h1)
    if None in (e20, e50, e200, m20, m50, adx, atr) or atr <= 0:
        return {"direction": "indefinida", "volatility": "indisponivel",
                "reason": "Indicadores de regime indisponíveis."}
    if e20 > e50 > e200 and m20 > m50 and adx >= 20:
        direction = "alta"
    elif e20 < e50 < e200 and m20 < m50 and adx >= 20:
        direction = "baixa"
    elif adx < 20 and abs(e20 - e50) <= 0.4 * atr:
        direction = "lateral"
    else:
        direction = "indefinida"
    recent = [_atr(h1[:end]) for end in range(max(215, len(h1) - 39), len(h1) + 1)]
    recent = [value for value in recent if value is not None]
    typical = sorted(recent)[len(recent) // 2] if recent else atr
    volatility = "alta" if atr > typical * 1.5 else "baixa" if atr < typical * 0.65 else "normal"
    return {"direction": direction, "volatility": volatility, "adx14": adx,
            "atr14_h1": atr, "ema20_h1": e20, "ema50_h1": e50, "ema200_h1": e200,
            "ema20_m15": m20, "ema50_m15": m50,
            "parameters_status": "hipotese_de_pesquisa"}


def _zones(m15: list[dict[str, Any]], atr: float) -> list[dict[str, Any]]:
    width = max(atr * 0.35, 1e-12)
    pivots: list[tuple[str, float, int, int]] = []
    # width=2: the pivot only becomes available after two subsequent bars close.
    for index in range(2, len(m15) - 2):
        window = m15[index - 2:index + 3]
        if all(m15[index]["high"] > row["high"] for row in window if row is not m15[index]):
            pivots.append(("resistance", m15[index]["high"],
                           m15[index + 2]["time"] + 900, index))
        if all(m15[index]["low"] < row["low"] for row in window if row is not m15[index]):
            pivots.append(("support", m15[index]["low"],
                           m15[index + 2]["time"] + 900, index))
    groups: list[dict[str, Any]] = []
    for side, level, confirmed_at, pivot_index in pivots:
        existing = next((item for item in groups if item["side"] == side
                         and abs(item["center"] - level) <= width), None)
        if existing:
            if pivot_index - existing["last_pivot_index"] < 6:
                continue
            n = existing["tests"]
            existing["center"] = (existing["center"] * n + level) / (n + 1)
            existing["tests"] = n + 1
            existing["confirmed_at"] = min(existing["confirmed_at"], confirmed_at)
            existing["last_confirmed_at"] = max(existing["last_confirmed_at"], confirmed_at)
            existing["last_pivot_index"] = pivot_index
        else:
            groups.append({"side": side, "center": level, "tests": 1,
                           "confirmed_at": confirmed_at,
                           "last_confirmed_at": confirmed_at,
                           "last_pivot_index": pivot_index})
    for item in groups:
        item["lower"] = item["center"] - width
        item["upper"] = item["center"] + width
        item["score_descriptive"] = min(35, 10 + 10 * min(item["tests"] - 1, 2))
        broken = [bar for bar in m15 if bar["time"] + 900 > item["last_confirmed_at"]
                  and ((item["side"] == "support" and bar["close"] < item["lower"] - 0.25 * atr)
                       or (item["side"] == "resistance" and bar["close"] > item["upper"] + 0.25 * atr))]
        item["state"] = "broken" if broken else "active"
        item["broken_at"] = broken[0]["time"] + 900 if broken else None
        item["id"] = hashlib.sha256(
            f'{item["side"]}:{item["confirmed_at"]}:{item["center"]:.8f}'.encode()
        ).hexdigest()[:16]
    return sorted(groups, key=lambda item: (item["side"], item["center"]))


def _nearest(zones: list[dict[str, Any]], side: str, price: float,
             max_distance: float, *, active_only: bool = False) -> dict[str, Any] | None:
    candidates = [item for item in zones if item["side"] == side
                  and (not active_only or item["state"] == "active")
                  and abs(item["center"] - price) <= max_distance]
    return min(candidates, key=lambda item: abs(item["center"] - price)) if candidates else None


def _entry(strategy: str, side: str, zone: dict[str, Any], latest: dict[str, Any],
           atr: float, reason: str, *, stop_extreme: float | None = None) -> dict[str, Any]:
    reference = latest["close"]
    if side == "BUY":
        stop = min(zone["lower"], stop_extreme if stop_extreme is not None else latest["low"]) - 0.15 * atr
        target = reference + 1.5 * (reference - stop)
    else:
        stop = max(zone["upper"], stop_extreme if stop_extreme is not None else latest["high"]) + 0.15 * atr
        target = reference - 1.5 * (stop - reference)
    return {"strategy": strategy, "side": side, "zone_id": zone["id"],
            "signal_bar_open_utc": latest["time"], "entry_reference": reference,
            "stop": stop, "target": target, "risk_reward_reference": 1.5,
            "score_descriptive": zone["score_descriptive"], "reason": reason,
            "status": "CANDIDATE_RESEARCH_ONLY"}


def evaluate_bundle(bundle: dict[str, Any], *, decision_time: int | None = None) -> dict[str, Any]:
    """Evaluate three research setups from data available at decision_time.

    This function has no order capability. Scores are descriptive, not probabilities.
    """
    symbol = str(bundle.get("symbol") or "")
    now = int(time.time() if decision_time is None else decision_time)
    frames = bundle.get("frames") or {}
    closed = {frame: _closed_bars(frames.get(frame), frame, now) for frame in FRAMES}
    missing = [frame for frame in FRAMES if len(closed[frame]) < MIN_BARS[frame]]
    basic = {"version": RULE_VERSION, "symbol": symbol, "decision_time_utc": now,
             "frame_last_closed": {frame: (rows[-1]["time"] if rows else None)
                                   for frame, rows in closed.items()},
             "mode": "research_only", "order_eligible": False}
    if missing:
        return {**basic, "status": "DADOS_INSUFICIENTES", "regime": None,
                "zones": [], "candidates": [], "rejections": [
                    {"code": "insufficient_history", "timeframes": missing}],
                "filter_counts": {"insufficient_history": 1}}
    m5 = closed["M5"]
    trigger = m5[-1]
    if now - (trigger["time"] + 300) > 600:
        return {**basic, "status": "DADOS_DESATUALIZADOS", "regime": None,
                "zones": [], "candidates": [], "rejections": [
                    {"code": "stale_trigger_bar"}], "filter_counts": {"stale_trigger_bar": 1}}
    atr = _atr(m5)
    atr15 = _atr(closed["M15"])
    if not atr or not atr15 or atr <= 0 or atr15 <= 0:
        return {**basic, "status": "DADOS_INSUFICIENTES", "regime": None,
                "zones": [], "candidates": [], "rejections": [
                    {"code": "atr_unavailable"}], "filter_counts": {"atr_unavailable": 1}}
    regime = _regime(closed["H1"], closed["M15"])
    zones = _zones(closed["M15"], atr15)
    candidates: list[dict[str, Any]] = []
    rejections: list[dict[str, Any]] = []
    body = abs(trigger["close"] - trigger["open"])
    candle_range = trigger["high"] - trigger["low"]
    strong = candle_range > 0 and body / candle_range >= 0.5
    bullish = trigger["close"] > trigger["open"]
    bearish = trigger["close"] < trigger["open"]
    lower_wick = min(trigger["open"], trigger["close"]) - trigger["low"]
    upper_wick = trigger["high"] - max(trigger["open"], trigger["close"])

    direction = regime["direction"]
    if direction in {"alta", "baixa"}:
        is_buy = direction == "alta"
        zone = _nearest(zones, "support" if is_buy else "resistance", trigger["close"],
                        1.5 * atr, active_only=True)
        rejected = "zone_missing"
        if zone:
            rejected = "pullback_not_confirmed"
            touched = (trigger["low"] <= zone["upper"] + 0.2 * atr if is_buy else
                       trigger["high"] >= zone["lower"] - 0.2 * atr)
            held = (trigger["close"] > zone["upper"] if is_buy else trigger["close"] < zone["lower"])
            candle_ok = (bullish and lower_wick >= body * 0.35 if is_buy else
                         bearish and upper_wick >= body * 0.35)
            if touched and held and strong and candle_ok:
                candidates.append(_entry("trend_pullback", "BUY" if is_buy else "SELL",
                                         zone, trigger, atr, "Retorno e rejeição confirmados em tendência."))
                rejected = ""
        if rejected:
            rejections.append({"strategy": "trend_pullback", "code": rejected})
    else:
        rejections.append({"strategy": "trend_pullback", "code": "regime_not_trending"})

    # A breakout must predate the current retest; the zone must predate the breakout.
    breakout_found = False
    for side, zone_side in (("BUY", "resistance"), ("SELL", "support")):
        zone = _nearest(zones, zone_side, trigger["close"], 2.0 * atr)
        if not zone or direction == "lateral":
            continue
        for earlier in reversed(m5[-7:-1]):
            if zone["last_confirmed_at"] > earlier["time"]:
                continue
            beyond = (earlier["close"] > zone["upper"] + 0.1 * atr if side == "BUY"
                      else earlier["close"] < zone["lower"] - 0.1 * atr)
            if not beyond:
                continue
            intervening = [bar for bar in m5 if earlier["time"] < bar["time"] < trigger["time"]]
            invalid = any(bar["close"] < zone["lower"] if side == "BUY"
                          else bar["close"] > zone["upper"] for bar in intervening)
            retested = (trigger["low"] <= zone["upper"] + 0.2 * atr and
                        trigger["close"] > zone["upper"] and bullish if side == "BUY" else
                        trigger["high"] >= zone["lower"] - 0.2 * atr and
                        trigger["close"] < zone["lower"] and bearish)
            if not invalid and retested and strong:
                candidates.append(_entry("breakout_retest", side, zone, trigger, atr,
                                         "Rompimento anterior, reteste e confirmação em candle fechado."))
                breakout_found = True
                break
        if breakout_found:
            break
    if not breakout_found:
        rejections.append({"strategy": "breakout_retest", "code": "breakout_retest_not_confirmed"})

    fakeout_found = False
    if direction == "lateral":
        for side, zone_side in (("SELL", "resistance"), ("BUY", "support")):
            zone = _nearest(zones, zone_side, trigger["close"], 1.5 * atr,
                            active_only=True)
            if not zone:
                continue
            failed = (trigger["high"] > zone["upper"] + 0.05 * atr and
                      zone["lower"] <= trigger["close"] <= zone["upper"] and
                      upper_wick >= body if side == "SELL" else
                      trigger["low"] < zone["lower"] - 0.05 * atr and
                      zone["lower"] <= trigger["close"] <= zone["upper"] and
                      lower_wick >= body)
            if failed:
                candidates.append(_entry("range_fakeout", side, zone, trigger, atr,
                                         "Falso rompimento fechou de volta na zona."))
                fakeout_found = True
                break
    if not fakeout_found:
        rejections.append({"strategy": "range_fakeout", "code": "range_fakeout_not_confirmed"})

    tick = bundle.get("tick") or {}
    bid, ask = _finite(tick.get("bid")), _finite(tick.get("ask"))
    spread_atr = ((ask - bid) / atr if bid is not None and ask is not None
                  and ask >= bid else None)
    cost_ok = spread_atr is not None and spread_atr <= MAX_SPREAD_ATR_M5
    if not cost_ok:
        rejections.append({"code": "spread_exceeds_research_threshold",
                           "spread_to_atr_m5": spread_atr,
                           "max_spread_to_atr_m5": MAX_SPREAD_ATR_M5})
    for candidate in candidates:
        if not cost_ok:
            candidate["status"] = "BLOCKED_COST"
        elif candidate["side"] == "BUY" and not candidate["stop"] < ask < candidate["target"]:
            candidate["status"] = "BLOCKED_PRICE"
        elif candidate["side"] == "SELL" and not candidate["target"] < bid < candidate["stop"]:
            candidate["status"] = "BLOCKED_PRICE"
    # Conflicting sides remain research observations, never become an order.
    if len({candidate["side"] for candidate in candidates}) > 1:
        for candidate in candidates:
            candidate["status"] = "CONFLICT"
        rejections.append({"code": "conflicting_strategies"})
    counts: dict[str, int] = {}
    for item in rejections:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    digest = hashlib.sha256(json.dumps(
        {"symbol": symbol, "frames": closed, "contract": bundle.get("contract") or {},
         "tick": {key: tick.get(key) for key in ("bid", "ask", "time")},
         "time_normalization": bundle.get("time_normalization") or {},
         "rule_version": RULE_VERSION}, sort_keys=True, separators=(",", ":"),
        default=str).encode()).hexdigest()
    return {**basic, "status": "EVALUATED", "regime": regime,
            "zones": zones[-20:], "zones_found": len(zones), "candidates": candidates,
            "rejections": rejections, "filter_counts": counts,
            "spread_to_atr_m5": spread_atr, "atr14_m5": atr,
            "data_sha256": digest, "parameters_status": "experimental_not_validated"}
