"""MetaTrader 5 connector implementation; ``MT5Gateway`` remains the legacy name."""

from ..mt5_gateway import MT5Gateway

MT5Connector = MT5Gateway

__all__ = ["MT5Connector"]
