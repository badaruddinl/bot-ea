from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
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
class OrderSendResult:
    accepted: bool
    detail: str
    retcode: int | None = None
    order: int | None = None
    deal: int | None = None
    volume: float | None = None
    price: float | None = None
    bid: float | None = None
    ask: float | None = None
    request_id: int | None = None
    retcode_external: int | None = None


@dataclass(slots=True)
class PriceTickSnapshot:
    symbol: str
    bid: float
    ask: float
    last: float = 0.0
    time: str | None = None


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


@dataclass(slots=True)
class TerminalStatusSnapshot:
    connected: bool
    trade_allowed: bool
    tradeapi_disabled: bool
    path: str = ""
    data_path: str = ""
    server: str = ""
    company: str = ""
    account_trade_allowed: bool = False
    account_trade_expert: bool = False


class MT5Adapter(Protocol):
    """Future integration seam for MetaTrader 5 terminal access."""

    def load_account_snapshot(self) -> AccountSnapshot:
        raise NotImplementedError

    def load_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        raise NotImplementedError

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        raise NotImplementedError

    def load_symbol_capabilities(self, symbol: str) -> SymbolCapabilitySnapshot:
        raise NotImplementedError

    def load_terminal_status(self) -> TerminalStatusSnapshot:
        raise NotImplementedError

    def load_available_symbols(self) -> list[str]:
        raise NotImplementedError

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float) -> MarginEstimate:
        raise NotImplementedError

    def validate_order(self, request: dict) -> OrderValidationResult:
        raise NotImplementedError

    def send_order(self, request: dict) -> OrderSendResult:
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

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        if symbol not in self._symbols:
            raise KeyError(f"unknown symbol: {symbol}")
        payload = self._symbols[symbol]
        point = float(payload.get("point", 0.0) or 0.0)
        spread_points = float(payload.get("spread", 0.0) or 0.0)
        ask = float(
            payload.get("ask")
            or payload.get("price")
            or payload.get("last")
            or 0.0
        )
        bid = float(payload.get("bid") or (ask - (spread_points * point) if ask and point else ask) or 0.0)
        if not ask and bid and point:
            ask = bid + (spread_points * point)
        return PriceTickSnapshot(
            symbol=symbol,
            bid=bid,
            ask=ask,
            last=float(payload.get("last", 0.0) or 0.0),
            time=payload.get("time"),
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

    def load_terminal_status(self) -> TerminalStatusSnapshot:
        account = self.load_account_snapshot()
        return TerminalStatusSnapshot(
            connected=True,
            trade_allowed=bool(account.trade_allowed),
            tradeapi_disabled=False,
            account_trade_allowed=bool(account.trade_allowed),
            account_trade_expert=bool(account.trade_expert),
        )

    def load_available_symbols(self) -> list[str]:
        return sorted(self._symbols.keys())

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

    def send_order(self, request: dict) -> OrderSendResult:
        validation = self.validate_order(request)
        if not validation.accepted:
            return OrderSendResult(
                accepted=False,
                detail=validation.detail,
                retcode=validation.retcode,
                volume=float(request.get("volume", 0.0) or 0.0),
                price=float(request.get("price", 0.0) or 0.0),
            )
        return OrderSendResult(
            accepted=True,
            detail="mock order filled",
            retcode=0,
            order=900001,
            deal=800001,
            volume=float(request.get("volume", 0.0) or 0.0),
            price=float(request.get("price", 0.0) or 0.0),
        )


class LiveMT5Adapter:
    """Read-only MT5 adapter plus broker-side preflight via the Python package."""

    _TRADE_MODE = {
        0: "disabled",
        1: "longonly",
        2: "shortonly",
        3: "closeonly",
        4: "full",
    }
    _EXECUTION_MODE = {
        0: "request",
        1: "instant",
        2: "market",
        3: "exchange",
    }
    _FILLING_FLAGS = {
        1: "fok",
        2: "ioc",
        4: "return",
    }
    _ORDER_MODE_FLAGS = {
        1: "market",
        2: "limit",
        4: "stop",
        8: "stop_limit",
        16: "sl",
        32: "tp",
        64: "close_by",
    }

    def __init__(
        self,
        *,
        path: str | None = None,
        login: int | None = None,
        password: str | None = None,
        server: str | None = None,
        timeout_ms: int = 60_000,
        portable: bool = False,
        mt5_module: Any | None = None,
    ) -> None:
        self.path = path
        self.login = login
        self.password = password
        self.server = server
        self.timeout_ms = timeout_ms
        self.portable = portable
        self._mt5 = mt5_module
        self._initialized = False

    def load_account_snapshot(self) -> AccountSnapshot:
        mt5 = self._ensure_initialized()
        account_info = mt5.account_info()
        if account_info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        return build_account_snapshot(account_info)

    def load_symbol_snapshot(self, symbol: str) -> SymbolSnapshot:
        mt5 = self._ensure_initialized()
        symbol_info = self._prepare_symbol(symbol)
        return build_symbol_snapshot(
            symbol_info,
            quote_session_active=self._is_trade_mode_active(getattr(symbol_info, "trade_mode", None)),
            trade_session_active=self._is_trade_mode_active(getattr(symbol_info, "trade_mode", None)),
            volatility_points=None,
        )

    def load_price_tick(self, symbol: str) -> PriceTickSnapshot:
        mt5 = self._ensure_initialized()
        self._prepare_symbol(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick({symbol}) failed: {mt5.last_error()}")
        return PriceTickSnapshot(
            symbol=symbol,
            bid=float(getattr(tick, "bid", 0.0) or 0.0),
            ask=float(getattr(tick, "ask", 0.0) or 0.0),
            last=float(getattr(tick, "last", 0.0) or 0.0),
            time=self._format_epoch(getattr(tick, "time", None)),
        )

    def load_symbol_capabilities(self, symbol: str) -> SymbolCapabilitySnapshot:
        symbol_info = self._prepare_symbol(symbol)
        return SymbolCapabilitySnapshot(
            symbol=symbol,
            trade_mode=self._map_trade_mode(getattr(symbol_info, "trade_mode", None)),
            order_mode=self._map_flags(getattr(symbol_info, "order_mode", None), self._ORDER_MODE_FLAGS),
            execution_mode=self._map_execution_mode(getattr(symbol_info, "trade_exemode", None)),
            filling_mode=self._map_flags(getattr(symbol_info, "filling_mode", None), self._FILLING_FLAGS),
            quote_session_active=self._is_trade_mode_active(getattr(symbol_info, "trade_mode", None)),
            trade_session_active=self._is_trade_mode_active(getattr(symbol_info, "trade_mode", None)),
            server_time=self._format_epoch(getattr(symbol_info, "time", None)),
        )

    def load_terminal_status(self) -> TerminalStatusSnapshot:
        mt5 = self._ensure_initialized()
        terminal_info = mt5.terminal_info()
        if terminal_info is None:
            raise RuntimeError(f"MT5 terminal_info() failed: {mt5.last_error()}")
        account_info = mt5.account_info()
        if account_info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        return TerminalStatusSnapshot(
            connected=bool(getattr(terminal_info, "connected", False)),
            trade_allowed=bool(getattr(terminal_info, "trade_allowed", False)),
            tradeapi_disabled=bool(getattr(terminal_info, "tradeapi_disabled", False)),
            path=str(getattr(terminal_info, "path", "") or ""),
            data_path=str(getattr(terminal_info, "data_path", "") or ""),
            server=str(getattr(account_info, "server", "") or ""),
            company=str(getattr(account_info, "company", "") or ""),
            account_trade_allowed=bool(getattr(account_info, "trade_allowed", False)),
            account_trade_expert=bool(getattr(account_info, "trade_expert", False)),
        )

    def load_available_symbols(self) -> list[str]:
        mt5 = self._ensure_initialized()
        symbols = mt5.symbols_get()
        if symbols is None:
            raise RuntimeError(f"MT5 symbols_get() failed: {mt5.last_error()}")
        return sorted(
            {
                str(getattr(symbol, "name", "") or "").strip()
                for symbol in symbols
                if str(getattr(symbol, "name", "") or "").strip()
            }
        )

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float) -> MarginEstimate:
        mt5 = self._ensure_initialized()
        if volume <= 0:
            return MarginEstimate(required_margin=0.0, success=False, detail="invalid volume")
        symbol_info = self._prepare_symbol(symbol)
        price_to_use = price if price > 0 else self._market_price(mt5, symbol, order_type)
        mt5_order_type = self._resolve_order_type(mt5, order_type)
        margin = mt5.order_calc_margin(mt5_order_type, symbol, volume, price_to_use)
        if margin is None:
            return MarginEstimate(required_margin=0.0, success=False, detail=f"order_calc_margin failed: {mt5.last_error()}")
        return MarginEstimate(
            required_margin=float(margin),
            success=True,
            detail=f"live margin estimate for {symbol_info.name} {order_type}",
        )

    def validate_order(self, request: dict) -> OrderValidationResult:
        mt5 = self._ensure_initialized()
        symbol_name = str(request.get("symbol", "") or "")
        if not symbol_name:
            return OrderValidationResult(accepted=False, detail="symbol missing", retcode=None)
        symbol_info = self._prepare_symbol(symbol_name)
        order_request = self._build_trade_request(mt5, symbol_info, request)
        result = mt5.order_check(order_request)
        if result is None:
            return OrderValidationResult(
                accepted=False,
                detail=f"order_check failed: {mt5.last_error()}",
                retcode=None,
            )
        retcode = int(getattr(result, "retcode", -1))
        comment = str(getattr(result, "comment", "") or "")
        return OrderValidationResult(
            accepted=retcode == 0,
            detail=comment or ("order_check accepted" if retcode == 0 else "order_check rejected"),
            projected_margin_free=float(getattr(result, "margin_free", 0.0) or 0.0),
            projected_margin_level=float(getattr(result, "margin_level", 0.0) or 0.0),
            retcode=retcode,
        )

    def send_order(self, request: dict) -> OrderSendResult:
        mt5 = self._ensure_initialized()
        symbol_name = str(request.get("symbol", "") or "")
        if not symbol_name:
            return OrderSendResult(accepted=False, detail="symbol missing", retcode=None)
        symbol_info = self._prepare_symbol(symbol_name)
        trade_request = self._build_trade_request(mt5, symbol_info, request)
        result = mt5.order_send(trade_request)
        if result is None:
            return OrderSendResult(
                accepted=False,
                detail=f"order_send failed: {mt5.last_error()}",
                retcode=None,
            )
        retcode = int(getattr(result, "retcode", -1))
        success_codes = {
            int(getattr(mt5, "TRADE_RETCODE_DONE", 10009)),
            int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008)),
        }
        return OrderSendResult(
            accepted=retcode in success_codes,
            detail=str(getattr(result, "comment", "") or ("order_send done" if retcode in success_codes else "order_send rejected")),
            retcode=retcode,
            order=getattr(result, "order", None),
            deal=getattr(result, "deal", None),
            volume=float(getattr(result, "volume", 0.0) or 0.0),
            price=float(getattr(result, "price", 0.0) or 0.0),
            bid=float(getattr(result, "bid", 0.0) or 0.0),
            ask=float(getattr(result, "ask", 0.0) or 0.0),
            request_id=getattr(result, "request_id", None),
            retcode_external=getattr(result, "retcode_external", None),
        )

    def shutdown(self) -> None:
        if self._initialized:
            self._mt5.shutdown()
            self._initialized = False

    def _ensure_initialized(self):
        mt5 = self._load_mt5_module()
        if self._initialized:
            return mt5

        init_kwargs: dict[str, Any] = {"timeout": self.timeout_ms, "portable": self.portable}
        if self.path:
            init_kwargs["path"] = self.path
        if self.login is not None:
            init_kwargs["login"] = self.login
        if self.password:
            init_kwargs["password"] = self.password
        if self.server:
            init_kwargs["server"] = self.server

        initialized = mt5.initialize(**init_kwargs) if init_kwargs else mt5.initialize()
        if not initialized:
            raise RuntimeError(f"MT5 initialize() failed: {mt5.last_error()}")
        self._initialized = True
        return mt5

    def _load_mt5_module(self):
        if self._mt5 is not None:
            return self._mt5
        try:
            import MetaTrader5 as mt5  # type: ignore
        except ImportError as exc:  # pragma: no cover - covered by behavior test via explicit injection path
            raise RuntimeError("MetaTrader5 Python package is not installed") from exc
        self._mt5 = mt5
        return mt5

    def _prepare_symbol(self, symbol: str):
        mt5 = self._ensure_initialized()
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            raise RuntimeError(f"MT5 symbol_info({symbol}) failed: {mt5.last_error()}")
        visible = bool(getattr(symbol_info, "visible", False))
        if not visible and not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"MT5 symbol_select({symbol}, True) failed: {mt5.last_error()}")
        if not visible:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                raise RuntimeError(f"MT5 symbol_info({symbol}) failed after select: {mt5.last_error()}")
        return symbol_info

    def _build_trade_request(self, mt5, symbol_info, request: dict) -> dict[str, Any]:
        order_type_raw = str(request.get("order_type", "buy") or "buy").lower()
        price = float(request.get("price", 0.0) or 0.0)
        if price <= 0:
            price = self._market_price(mt5, getattr(symbol_info, "name", ""), order_type_raw)

        trade_request: dict[str, Any] = {
            "action": getattr(mt5, "TRADE_ACTION_DEAL"),
            "symbol": getattr(symbol_info, "name", ""),
            "volume": float(request.get("volume", 0.0) or 0.0),
            "type": self._resolve_order_type(mt5, order_type_raw),
            "deviation": int(request.get("deviation", 20) or 20),
            "magic": int(request.get("magic", 234000) or 234000),
            "comment": str(request.get("comment", "bot-ea preflight") or "bot-ea preflight"),
            "type_time": getattr(mt5, "ORDER_TIME_GTC"),
            "type_filling": self._resolve_filling_type(mt5, symbol_info),
        }

        if self._map_execution_mode(getattr(symbol_info, "trade_exemode", None)) != "market":
            trade_request["price"] = price

        stop_distance_points = float(request.get("stop_distance_points", 0.0) or 0.0)
        if stop_distance_points > 0:
            point = float(getattr(symbol_info, "point", 0.0) or 0.0)
            if point > 0:
                distance = stop_distance_points * point
                if order_type_raw == "sell":
                    trade_request["sl"] = price + distance
                else:
                    trade_request["sl"] = price - distance

        if request.get("sl") is not None:
            trade_request["sl"] = float(request["sl"])
        if request.get("tp") is not None:
            trade_request["tp"] = float(request["tp"])
        return trade_request

    @staticmethod
    def _format_epoch(value: int | float | None) -> str | None:
        if not value:
            return None
        return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()

    @classmethod
    def _map_trade_mode(cls, value: Any) -> str:
        try:
            return cls._TRADE_MODE.get(int(value), str(value))
        except (TypeError, ValueError):
            return str(value or "")

    @classmethod
    def _map_execution_mode(cls, value: Any) -> str:
        try:
            return cls._EXECUTION_MODE.get(int(value), str(value))
        except (TypeError, ValueError):
            return str(value or "")

    @classmethod
    def _map_flags(cls, value: Any, mapping: dict[int, str]) -> str:
        try:
            raw = int(value)
        except (TypeError, ValueError):
            return str(value or "")
        labels = [label for flag, label in mapping.items() if raw & flag]
        return "|".join(labels) if labels else str(raw)

    @classmethod
    def _is_trade_mode_active(cls, value: Any) -> bool:
        return cls._map_trade_mode(value) != "disabled"

    @staticmethod
    def _resolve_order_type(mt5, order_type: str) -> int:
        if order_type == "sell":
            return getattr(mt5, "ORDER_TYPE_SELL")
        return getattr(mt5, "ORDER_TYPE_BUY")

    def _resolve_filling_type(self, mt5, symbol_info) -> int:
        filling_mode = int(getattr(symbol_info, "filling_mode", 0) or 0)
        execution_mode = self._map_execution_mode(getattr(symbol_info, "trade_exemode", None))
        if execution_mode != "market" and filling_mode & 4 and hasattr(mt5, "ORDER_FILLING_RETURN"):
            return getattr(mt5, "ORDER_FILLING_RETURN")
        if filling_mode & 1 and hasattr(mt5, "ORDER_FILLING_FOK"):
            return getattr(mt5, "ORDER_FILLING_FOK")
        if filling_mode & 2 and hasattr(mt5, "ORDER_FILLING_IOC"):
            return getattr(mt5, "ORDER_FILLING_IOC")
        return getattr(mt5, "ORDER_FILLING_RETURN", getattr(mt5, "ORDER_FILLING_FOK"))

    def _market_price(self, mt5, symbol: str, order_type: str) -> float:
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick({symbol}) failed: {mt5.last_error()}")
        if order_type == "sell":
            return float(getattr(tick, "bid", 0.0) or 0.0)
        return float(getattr(tick, "ask", 0.0) or 0.0)
