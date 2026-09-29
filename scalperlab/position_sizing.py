"""Broker-aware position sizing used for preview and execution."""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
import math

from .risk_settings import validate_policy


def valid_volume(volume: float, symbol) -> bool:
    step = float(symbol.volume_step)
    if not math.isfinite(volume) or step <= 0 or not float(symbol.volume_min) <= volume <= float(symbol.volume_max):
        return False
    return abs(volume / step - round(volume / step)) < 1e-7


def size_order(mt5, symbol, side: str, entry: float, stop: float, budget: float, policy: dict) -> dict:
    p = validate_policy(policy)
    values = [entry, stop, budget, float(symbol.volume_min), float(symbol.volume_step), float(symbol.volume_max)]
    if side not in {"BUY", "SELL"} or any(not math.isfinite(x) or x <= 0 for x in values):
        return {"ok": False, "detail": "Preço, contrato ou orçamento inválido."}
    if (side == "BUY" and stop >= entry) or (side == "SELL" and stop <= entry):
        return {"ok": False, "detail": "Stop deve representar uma perda no lado escolhido."}
    order_type = mt5.ORDER_TYPE_BUY if side == "BUY" else mt5.ORDER_TYPE_SELL
    minimum = float(symbol.volume_min)
    ref_loss = mt5.order_calc_profit(order_type, symbol.name, minimum, entry, stop)
    if ref_loss is None or not math.isfinite(float(ref_loss)) or float(ref_loss) >= 0:
        return {"ok": False, "detail": "Não foi possível estimar a perda até o stop."}
    loss_per_lot = abs(float(ref_loss)) / minimum
    ceiling = min(p["max_volume"], float(symbol.volume_max))
    directional_limit = float(getattr(symbol, "volume_limit", 0) or 0)
    if directional_limit > 0:
        ceiling = min(ceiling, directional_limit)
    if p["sizing_mode"] == "fixed_lot":
        volume = p["fixed_volume"]
        if volume > ceiling or not valid_volume(volume, symbol):
            return {"ok": False, "detail": f"Lote fixo incompatível: mínimo {minimum:g}, máximo permitido {ceiling:g}, passo {symbol.volume_step:g}."}
    else:
        raw = min(ceiling, budget / loss_per_lot)
        step = Decimal(str(symbol.volume_step))
        volume = float((Decimal(str(raw)) / step).to_integral_value(rounding=ROUND_FLOOR) * step)
    if volume < minimum:
        return {"ok": False, "detail": f"Lote permitido abaixo do mínimo {minimum:g}; confira orçamento de risco e lote máximo."}
    loss = mt5.order_calc_profit(order_type, symbol.name, volume, entry, stop)
    if loss is None or not math.isfinite(float(loss)) or not 0 < -float(loss) <= budget * 1.000001:
        return {"ok": False, "detail": "Lote excede o orçamento de perda até o stop."}
    account = mt5.account_info()
    free = float(getattr(account, "margin_free", -1))
    margin = mt5.order_calc_margin(order_type, symbol.name, volume, entry)
    if margin is None or not math.isfinite(float(margin)) or float(margin) < 0 or not math.isfinite(free) or free < 0:
        return {"ok": False, "detail": "Margem indisponível para dimensionar a operação."}
    if float(margin) > free * (1 - p["margin_reserve_pct"] / 100):
        return {"ok": False, "detail": "Lote exige margem acima da reserva configurada; reduza o lote ou o orçamento."}
    return {"ok": True, "volume": volume, "estimated_loss": -float(loss),
            "risk_cash": budget, "margin_required": float(margin), "margin_free_after": free - float(margin),
            "volume_min": minimum, "volume_step": float(symbol.volume_step), "volume_max": ceiling,
            "policy": p, "policy_version": policy.get("version"),
            "detail": "Prévia calculada; preço, risco e margem serão conferidos novamente no envio."}
