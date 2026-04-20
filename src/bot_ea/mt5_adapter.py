from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class MarginEstimate:
    required_margin: float
    success: bool
    detail: str


class MT5Adapter(Protocol):
    """Future integration seam for MetaTrader 5 terminal access."""

    def load_account_snapshot(self):
        raise NotImplementedError

    def load_symbol_snapshot(self, symbol: str):
        raise NotImplementedError

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float) -> MarginEstimate:
        raise NotImplementedError

    def validate_order(self, request: dict) -> dict:
        raise NotImplementedError
