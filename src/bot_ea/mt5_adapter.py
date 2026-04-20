from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .models import AccountSnapshot, SymbolSnapshot
from .mt5_snapshots import build_account_snapshot, build_symbol_snapshot


@dataclass(slots=True)
class MarginEstimate:
    required_margin: float
    success: bool
    detail: str


@dataclass(slots=True)
class OrderValidationResult:
    accepted: bool
    detail: str
    projected_margin_free: float | None = None
    projected_margin_level: float | None = None
    retcode: int | None = None


@dataclass(slots=True)
class SymbolCapabilitySnapshot:
    symbol: str
    trade_mode: str = ""
    order_mode: str = ""
    execution_mode: str = ""
    filling_mode: str = ""
    quote_session_active: bool = True
    trade_session_active: bool = True
    server_time: str | None = None
    session_windows: list[str] = field(default_factory=list)


class MT5Adapter(Protocol):
    """Future integration seam for MetaTrader 5 terminal access."""

    def load_account_snapshot(self) -> AccountSnapshot:
        raise NotImplementedError

    def load_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        raise NotImplementedError

    def load_symbol_capabilities(self, symbol: str) -> SymbolCapabilitySnapshot:
        raise NotImplementedError

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float) -> MarginEstimate:
        raise NotImplementedError

    def validate_order(self, request: dict) -> OrderValidationResult:
        raise NotImplementedError


class MockMT5Adapter:
    """In-memory adapter for local development before MT5 is installed."""

    def __init__(
        self,
        *,
        account_info: dict,
        symbols: dict[str, dict],
        capabilities: dict[str, dict] | None = None,
    ) -> None:
        self._account_info = account_info
        self._symbols = symbols
        self._capabilities = capabilities or {}

    def load_account_snapshot(self) -> AccountSnapshot:
        return build_account_snapshot(self._account_info)

    def load_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        if symbol not in self._symbols:
            raise KeyError(f"unknown symbol: {symbol}")
        payload = self._symbols[symbol]
        capability = self._capabilities.get(symbol, {})
        return build_symbol_snapshot(
            payload,
            quote_session_active=bool(capability.get("quote_session_active", True)),
            trade_session_active=bool(capability.get("trade_session_active", True)),
            volatility_points=payload.get("volatility_points"),
        )

    def load_symbol_capabilities(self, symbol: str) -> SymbolCapabilitySnapshot:
        if symbol not in self._symbols:
            raise KeyError(f"unknown symbol: {symbol}")
        capability = self._capabilities.get(symbol, {})
        return SymbolCapabilitySnapshot(
            symbol=symbol,
            trade_mode=str(capability.get("trade_mode", "full")),
            order_mode=str(capability.get("order_mode", "market")),
            execution_mode=str(capability.get("execution_mode", "market")),
            filling_mode=str(capability.get("filling_mode", "fok")),
            quote_session_active=bool(capability.get("quote_session_active", True)),
            trade_session_active=bool(capability.get("trade_session_active", True)),
            server_time=capability.get("server_time"),
            session_windows=list(capability.get("session_windows", [])),
        )

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float) -> MarginEstimate:
        snapshot = self.load_symbol_snapshot(symbol)
        if volume <= 0 or price <= 0:
            return MarginEstimate(required_margin=0.0, success=False, detail="invalid volume or price")
        contract_multiplier = max(snapshot.tick_value / max(snapshot.tick_size, snapshot.point, 1e-12), 1.0)
        required_margin = volume * price * contract_multiplier * 0.01
        return MarginEstimate(required_margin=required_margin, success=True, detail=f"mock estimate for {order_type}")

    def validate_order(self, request: dict) -> OrderValidationResult:
        symbol_name = str(request.get("symbol", ""))
        volume = float(request.get("volume", 0.0) or 0.0)
        stop_distance_points = float(request.get("stop_distance_points", 0.0) or 0.0)
        price = float(request.get("price", 0.0) or 0.0)

        if symbol_name not in self._symbols:
            return OrderValidationResult(accepted=False, detail="unknown symbol", retcode=404)

        snapshot = self.load_symbol_snapshot(symbol_name)
        if volume < snapshot.volume_min:
            return OrderValidationResult(accepted=False, detail="volume below minimum", retcode=10014)
        if volume > snapshot.volume_max:
            return OrderValidationResult(accepted=False, detail="volume above maximum", retcode=10014)
        if stop_distance_points < snapshot.stops_level_points:
            return OrderValidationResult(accepted=False, detail="stop distance below broker stop level", retcode=10016)

        margin = self.estimate_margin(symbol_name, volume, str(request.get("order_type", "market")), price)
        account = self.load_account_snapshot()
        projected_margin_free = account.free_margin - margin.required_margin
        if projected_margin_free < 0:
            return OrderValidationResult(
                accepted=False,
                detail="insufficient free margin",
                projected_margin_free=projected_margin_free,
                projected_margin_level=account.margin_level,
                retcode=10019,
            )
        return OrderValidationResult(
            accepted=True,
            detail="mock validation accepted",
            projected_margin_free=projected_margin_free,
            projected_margin_level=account.margin_level,
            retcode=0,
        )
        raise NotImplementedError
