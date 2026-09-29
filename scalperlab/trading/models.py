from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConnectorStatus:
    terminal_id: str
    connected: bool
    status: str
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class Symbol:
    """Broker-specific instrument with a stable internal identity."""

    canonical_symbol: str
    broker_symbol: str
    digits: int
    tick_size: float
    volume_min: float
    volume_step: float
    trade_enabled: bool
    volume_max: float = 0.0
    volume_limit: float = 0.0
    visible: bool = False
    asset_class: str | None = None
    base: str | None = None
    quote: str | None = None

    @classmethod
    def from_broker_info(cls, info: Any, canonical_symbol: str | None = None) -> "Symbol":
        broker_symbol = str(getattr(info, "name", ""))
        if not broker_symbol:
            raise ValueError("Informação do broker sem nome de símbolo.")
        trade_mode = int(getattr(info, "trade_mode", 0))
        return cls(
            canonical_symbol=(canonical_symbol or broker_symbol).upper(),
            broker_symbol=broker_symbol,
            digits=int(getattr(info, "digits", 0)),
            tick_size=float(getattr(info, "trade_tick_size", getattr(info, "point", 0.0))),
            volume_min=float(getattr(info, "volume_min", 0.0)),
            volume_step=float(getattr(info, "volume_step", 0.0)),
            trade_enabled=trade_mode in {1, 2, 4},
            volume_max=float(getattr(info, "volume_max", 0.0)),
            volume_limit=float(getattr(info, "volume_limit", 0.0)),
            visible=bool(getattr(info, "visible", False)),
            base=getattr(info, "currency_base", None) or None,
            quote=getattr(info, "currency_profit", None) or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_symbol": self.canonical_symbol,
            "broker_symbol": self.broker_symbol,
            "digits": self.digits,
            "tick_size": self.tick_size,
            "volume_min": self.volume_min,
            "volume_step": self.volume_step,
            "trade_enabled": self.trade_enabled,
            "volume_max": self.volume_max,
            "volume_limit": self.volume_limit,
            "visible": self.visible,
            "asset_class": self.asset_class,
            "base": self.base,
            "quote": self.quote,
        }
