from __future__ import annotations

import contextlib
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite
from pathlib import Path
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
    execution_status: str = ""
    outcome_unknown: bool = False


@dataclass(slots=True)
class PositionProtectionResult:
    """Observed result of a broker-side SL/TP protection change.

    ``accepted`` is deliberately stricter than merely receiving a response: a
    live request must return ``TRADE_RETCODE_DONE`` and the requested SL/TP must
    be visible on the position afterwards.  ``postcondition_met`` is kept
    separate so callers can reconcile safely after an ambiguous broker result.
    """

    accepted: bool
    detail: str
    retcode: int | None = None
    position_ticket: int | None = None
    position_identifier: int | None = None
    sl: float | None = None
    tp: float | None = None
    changed: bool = False
    postcondition_met: bool = False
    outcome_unknown: bool = False
    order: int | None = None
    deal: int | None = None
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


@dataclass(slots=True)
class AccountFingerprintSnapshot:
    login: str
    server: str
    broker: str = ""
    is_live: bool | None = None
    margin_mode: str = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class MutationAccountBinding:
    """Immutable account/terminal identity required for a broker mutation."""

    login: str
    server: str
    account_scope: str
    margin_mode: str
    broker: str = ""
    terminal_path: str = ""
    terminal_data_path: str = ""


@dataclass(slots=True)
class OpenPositionSnapshot:
    ticket: int
    symbol: str
    side: str
    volume: float
    price_open: float
    sl: float
    tp: float
    profit: float
    opened_at: str | None
    magic: int
    comment: str
    # MT5's position identifier remains stable across the position lifecycle,
    # while the ticket can change after some broker-side service operations.
    # The default keeps construction by older integrations source-compatible.
    position_identifier: int | None = None

    def __post_init__(self) -> None:
        if self.position_identifier is None:
            self.position_identifier = self.ticket


@dataclass(slots=True)
class OpenOrderSnapshot:
    """A sanitized active MT5 order returned by ``orders_get``.

    MT5 uses "order" for both pending entry instructions and short-lived
    active requests.  Deployment safety must account for every row returned by
    ``orders_get``: an apparently flat position book is not flat when one of
    these orders can still fill.
    """

    ticket: int
    symbol: str
    order_type: str
    state: str
    volume_initial: float
    volume_current: float
    price_open: float
    price_stoplimit: float
    sl: float
    tp: float
    setup_at: str | None
    expiration_at: str | None
    magic: int
    position_ticket: int | None = None


@dataclass(slots=True)
class DealSnapshot:
    ticket: int
    position_ticket: int
    symbol: str
    side: str
    entry: str
    volume: float
    price: float
    profit: float
    commission: float
    swap: float
    reason: str
    occurred_at: str | None
    magic: int
    comment: str
    # Some brokers charge a separate DEAL_FEE in addition to commission/swap.
    # Keep a default for source compatibility with existing test adapters.
    fee: float = 0.0


def canonical_account_margin_mode(value: Any, *, mt5_module: Any | None = None) -> str:
    """Return a stable MT5 account accounting model name.

    MT5 exposes integer constants, while mocks/configuration often expose their
    symbolic names.  Unknown values deliberately stay UNKNOWN so an automated
    entry cannot silently assume hedging semantics.
    """

    if value is None:
        return "UNKNOWN"
    text = str(value).strip().upper()
    aliases = {
        "HEDGING": "HEDGING",
        "RETAIL_HEDGING": "HEDGING",
        "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING": "HEDGING",
        "NETTING": "NETTING",
        "RETAIL_NETTING": "NETTING",
        "ACCOUNT_MARGIN_MODE_RETAIL_NETTING": "NETTING",
        "EXCHANGE": "EXCHANGE",
        "ACCOUNT_MARGIN_MODE_EXCHANGE": "EXCHANGE",
    }
    if text in aliases:
        return aliases[text]

    constants = (
        ("ACCOUNT_MARGIN_MODE_RETAIL_HEDGING", "HEDGING"),
        ("ACCOUNT_MARGIN_MODE_RETAIL_NETTING", "NETTING"),
        ("ACCOUNT_MARGIN_MODE_EXCHANGE", "EXCHANGE"),
    )
    if mt5_module is not None:
        for constant_name, label in constants:
            constant = getattr(mt5_module, constant_name, None)
            if constant is not None and value == constant:
                return label

    # These are the documented MT5 enum values.  Keep this fallback for account
    # dictionaries and old Python bindings that do not export the constants.
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        return "UNKNOWN"
    return {0: "NETTING", 1: "EXCHANGE", 2: "HEDGING"}.get(numeric, "UNKNOWN")


def _canonical_path_text(value: str) -> str:
    if not str(value or "").strip():
        return ""
    return str(Path(value).expanduser().resolve(strict=False)).casefold()


def _terminal_install_path_text(value: str) -> str:
    path = Path(value).expanduser()
    if path.suffix.casefold() == ".exe":
        path = path.parent
    return str(path.resolve(strict=False)).casefold()


def _find_position_snapshot(
    positions: list[OpenPositionSnapshot],
    *,
    position_ticket: int | None,
    position_identifier: int | None,
) -> OpenPositionSnapshot | None:
    if position_ticket is None and position_identifier is None:
        return None
    if position_identifier is not None:
        for position in positions:
            stable_identifier = (
                position.position_identifier
                if position.position_identifier is not None
                else position.ticket
            )
            if stable_identifier == int(position_identifier):
                return position
        return None
    for position in positions:
        if position_ticket is not None and position.ticket != int(position_ticket):
            continue
        return position
    return None


def _validate_protection_request(
    *,
    position_ticket: int | None,
    position_identifier: int | None,
    sl: float | None,
    tp: float | None,
) -> str | None:
    if position_ticket is None and position_identifier is None:
        return "position ticket or stable position identifier is required"
    if position_ticket is not None and int(position_ticket) <= 0:
        return "position ticket must be positive"
    if position_identifier is not None and int(position_identifier) <= 0:
        return "position identifier must be positive"
    if sl is None and tp is None:
        return "at least one of sl or tp must be provided"
    for label, value in (("sl", sl), ("tp", tp)):
        if value is None:
            continue
        numeric = float(value)
        if not isfinite(numeric) or numeric < 0:
            return f"{label} must be a finite non-negative price"
    return None


def _position_price_tolerance(symbol_info: Any) -> float:
    if isinstance(symbol_info, dict):
        raw_point = symbol_info.get("point", 0.0)
    else:
        raw_point = getattr(symbol_info, "point", 0.0)
    point = float(raw_point or 0.0)
    return max(point / 2.0, 1e-9)


def _normalize_position_price(value: float, symbol_info: Any) -> float:
    if value == 0:
        return 0.0
    if isinstance(symbol_info, dict):
        raw_tick_size = symbol_info.get("trade_tick_size") or symbol_info.get("point")
        raw_digits = symbol_info.get("digits")
        raw_point = symbol_info.get("point")
    else:
        raw_tick_size = getattr(symbol_info, "trade_tick_size", None) or getattr(
            symbol_info, "point", None
        )
        raw_digits = getattr(symbol_info, "digits", None)
        raw_point = getattr(symbol_info, "point", None)
    tick_size = float(raw_tick_size or 0.0)
    if tick_size <= 0:
        raise ValueError("symbol tick size is unavailable for protection normalization")
    if raw_digits is None:
        point_text = format(float(raw_point or tick_size), ".12f").rstrip("0")
        digits = len(point_text.partition(".")[2])
    else:
        digits = int(raw_digits)
    value_decimal = Decimal(str(value))
    tick_decimal = Decimal(str(tick_size))
    ticks = (value_decimal / tick_decimal).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return round(float(ticks * tick_decimal), digits)


def _protection_matches(
    position: OpenPositionSnapshot,
    *,
    sl: float,
    tp: float,
    tolerance: float,
) -> bool:
    return abs(position.sl - sl) <= tolerance and abs(position.tp - tp) <= tolerance


def _protection_result(
    position: OpenPositionSnapshot,
    *,
    accepted: bool,
    detail: str,
    retcode: int | None,
    changed: bool,
    postcondition_met: bool,
    outcome_unknown: bool = False,
    order: int | None = None,
    deal: int | None = None,
    request_id: int | None = None,
    retcode_external: int | None = None,
) -> PositionProtectionResult:
    return PositionProtectionResult(
        accepted=accepted,
        detail=detail,
        retcode=retcode,
        position_ticket=position.ticket,
        position_identifier=(
            position.position_identifier
            if position.position_identifier is not None
            else position.ticket
        ),
        sl=position.sl,
        tp=position.tp,
        changed=changed,
        postcondition_met=postcondition_met,
        outcome_unknown=outcome_unknown,
        order=order,
        deal=deal,
        request_id=request_id,
        retcode_external=retcode_external,
    )


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

    def load_account_fingerprint(self) -> AccountFingerprintSnapshot:
        raise NotImplementedError

    def load_available_symbols(self) -> list[str]:
        raise NotImplementedError

    def estimate_margin(self, symbol: str, volume: float, order_type: str, price: float) -> MarginEstimate:
        raise NotImplementedError

    def validate_order(self, request: dict) -> OrderValidationResult:
        raise NotImplementedError

    def send_order(self, request: dict) -> OrderSendResult:
        raise NotImplementedError

    def load_open_positions(self, *, symbol: str | None = None) -> list[OpenPositionSnapshot]:
        raise NotImplementedError

    def load_open_orders(self, *, symbol: str | None = None) -> list[OpenOrderSnapshot]:
        raise NotImplementedError

    def find_open_position(
        self,
        *,
        position_ticket: int | None = None,
        position_identifier: int | None = None,
        symbol: str | None = None,
    ) -> OpenPositionSnapshot | None:
        raise NotImplementedError

    def modify_position_protection(
        self,
        position_ticket: int | None = None,
        *,
        position_identifier: int | None = None,
        sl: float | None = None,
        tp: float | None = None,
        mutation_binding: MutationAccountBinding | None = None,
    ) -> PositionProtectionResult:
        raise NotImplementedError

    def load_deals(self, *, since: datetime, symbol: str | None = None) -> list[DealSnapshot]:
        raise NotImplementedError


class MockMT5Adapter:
    """In-memory adapter for local development before MT5 is installed."""

    def __init__(
        self,
        *,
        account_info: dict,
        symbols: dict[str, dict],
        capabilities: dict[str, dict] | None = None,
        open_positions: list[OpenPositionSnapshot | dict[str, Any]] | None = None,
        open_orders: list[OpenOrderSnapshot | dict[str, Any]] | None = None,
    ) -> None:
        self._account_info = account_info
        self._symbols = symbols
        self._capabilities = capabilities or {}
        self._open_positions = [self._coerce_open_position(row) for row in (open_positions or [])]
        self._open_orders = [self._coerce_open_order(row) for row in (open_orders or [])]

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

    def load_account_fingerprint(self) -> AccountFingerprintSnapshot:
        server = str(self._account_info.get("server", "") or "")
        broker = str(self._account_info.get("company", "") or self._account_info.get("broker", "") or "")
        return AccountFingerprintSnapshot(
            login=str(self._account_info.get("login", "") or ""),
            server=server,
            broker=broker,
            is_live=LiveMT5Adapter._infer_is_live(server=server, broker=broker),
            margin_mode=canonical_account_margin_mode(
                self._account_info.get("margin_mode")
            ),
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
        action = str(request.get("action", "open") or "open").lower()
        volume = float(request.get("volume", 0.0) or 0.0)
        stop_distance_points = float(request.get("stop_distance_points", 0.0) or 0.0)
        price = float(request.get("price", 0.0) or 0.0)

        if action == "cancel_pending":
            order_ticket = request.get("order_ticket") or request.get("order")
            if not order_ticket:
                return OrderValidationResult(accepted=False, detail="order ticket missing", retcode=404)
            return OrderValidationResult(accepted=True, detail="mock cancel accepted", retcode=0)

        if symbol_name not in self._symbols:
            return OrderValidationResult(accepted=False, detail="unknown symbol", retcode=404)

        snapshot = self.load_symbol_snapshot(symbol_name)
        if volume < snapshot.volume_min:
            return OrderValidationResult(accepted=False, detail="volume below minimum", retcode=10014)
        if volume > snapshot.volume_max:
            return OrderValidationResult(accepted=False, detail="volume above maximum", retcode=10014)
        if action in {"close", "reduce"}:
            position_ticket = request.get("position_ticket") or request.get("position")
            if not position_ticket:
                return OrderValidationResult(accepted=False, detail="position ticket missing", retcode=404)
        elif stop_distance_points < snapshot.stops_level_points:
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
        action = str(request.get("action", "open") or "open").lower()
        validation = self.validate_order(request)
        if not validation.accepted:
            return OrderSendResult(
                accepted=False,
                detail=validation.detail,
                retcode=validation.retcode,
                volume=float(request.get("volume", 0.0) or 0.0),
                price=float(request.get("price", 0.0) or 0.0),
                execution_status="REJECTED",
            )
        if action == "cancel_pending":
            return OrderSendResult(
                accepted=True,
                detail="mock pending order cancelled",
                retcode=0,
                order=int(request.get("order_ticket") or request.get("order") or 900001),
                deal=None,
                volume=0.0,
                price=0.0,
                execution_status="FILLED",
            )
        return OrderSendResult(
            accepted=True,
            detail="mock order filled",
            retcode=0,
            order=900001,
            deal=800001,
            volume=float(request.get("volume", 0.0) or 0.0),
            price=float(request.get("price", 0.0) or 0.0),
            execution_status="FILLED",
        )

    def load_open_positions(self, *, symbol: str | None = None) -> list[OpenPositionSnapshot]:
        return [
            replace(position)
            for position in self._open_positions
            if symbol is None or position.symbol == symbol
        ]

    def load_open_orders(self, *, symbol: str | None = None) -> list[OpenOrderSnapshot]:
        return [
            replace(order)
            for order in self._open_orders
            if symbol is None or order.symbol == symbol
        ]

    def find_open_position(
        self,
        *,
        position_ticket: int | None = None,
        position_identifier: int | None = None,
        symbol: str | None = None,
    ) -> OpenPositionSnapshot | None:
        return _find_position_snapshot(
            self.load_open_positions(symbol=symbol),
            position_ticket=position_ticket,
            position_identifier=position_identifier,
        )

    def modify_position_protection(
        self,
        position_ticket: int | None = None,
        *,
        position_identifier: int | None = None,
        sl: float | None = None,
        tp: float | None = None,
        mutation_binding: MutationAccountBinding | None = None,
    ) -> PositionProtectionResult:
        del mutation_binding
        invalid = _validate_protection_request(
            position_ticket=position_ticket,
            position_identifier=position_identifier,
            sl=sl,
            tp=tp,
        )
        if invalid:
            return PositionProtectionResult(accepted=False, detail=invalid)

        position = self.find_open_position(
            position_ticket=position_ticket,
            position_identifier=position_identifier,
        )
        if position is None:
            return PositionProtectionResult(
                accepted=False,
                detail="open position not found",
                position_ticket=position_ticket,
                position_identifier=position_identifier,
            )

        symbol_info = self._symbols.get(position.symbol, {})
        desired_sl = _normalize_position_price(
            position.sl if sl is None else float(sl), symbol_info
        )
        desired_tp = _normalize_position_price(
            position.tp if tp is None else float(tp), symbol_info
        )
        tolerance = _position_price_tolerance(symbol_info)
        already_applied = _protection_matches(
            position,
            sl=desired_sl,
            tp=desired_tp,
            tolerance=tolerance,
        )
        if already_applied:
            return _protection_result(
                position,
                accepted=True,
                detail="position protection already matches requested values",
                retcode=None,
                changed=False,
                postcondition_met=True,
            )

        for index, current in enumerate(self._open_positions):
            if current.ticket == position.ticket:
                self._open_positions[index] = replace(current, sl=desired_sl, tp=desired_tp)
                break
        observed = self.find_open_position(position_ticket=position.ticket)
        postcondition_met = bool(
            observed
            and _protection_matches(
                observed,
                sl=desired_sl,
                tp=desired_tp,
                tolerance=tolerance,
            )
        )
        if observed is None:
            observed = replace(position, sl=desired_sl, tp=desired_tp)
        return _protection_result(
            observed,
            accepted=postcondition_met,
            detail=(
                "mock position protection updated"
                if postcondition_met
                else "mock position protection postcondition not met"
            ),
            retcode=0,
            changed=True,
            postcondition_met=postcondition_met,
        )

    def load_deals(self, *, since: datetime, symbol: str | None = None) -> list[DealSnapshot]:
        return []

    @staticmethod
    def _coerce_open_position(row: OpenPositionSnapshot | dict[str, Any]) -> OpenPositionSnapshot:
        if isinstance(row, OpenPositionSnapshot):
            if row.position_identifier is not None:
                return replace(row)
            return replace(row, position_identifier=row.ticket)
        ticket = int(row.get("ticket", 0) or 0)
        return OpenPositionSnapshot(
            ticket=ticket,
            symbol=str(row.get("symbol", "") or ""),
            side=str(row.get("side", "") or ""),
            volume=float(row.get("volume", 0.0) or 0.0),
            price_open=float(row.get("price_open", 0.0) or 0.0),
            sl=float(row.get("sl", 0.0) or 0.0),
            tp=float(row.get("tp", 0.0) or 0.0),
            profit=float(row.get("profit", 0.0) or 0.0),
            opened_at=row.get("opened_at"),
            magic=int(row.get("magic", 0) or 0),
            comment=str(row.get("comment", "") or ""),
            position_identifier=int(row.get("position_identifier", ticket) or ticket),
        )

    @staticmethod
    def _coerce_open_order(row: OpenOrderSnapshot | dict[str, Any]) -> OpenOrderSnapshot:
        if isinstance(row, OpenOrderSnapshot):
            return replace(row)
        position_ticket = row.get("position_ticket")
        return OpenOrderSnapshot(
            ticket=int(row.get("ticket", 0) or 0),
            symbol=str(row.get("symbol", "") or ""),
            order_type=str(row.get("order_type", "unknown") or "unknown"),
            state=str(row.get("state", "unknown") or "unknown"),
            volume_initial=float(row.get("volume_initial", 0.0) or 0.0),
            volume_current=float(row.get("volume_current", 0.0) or 0.0),
            price_open=float(row.get("price_open", 0.0) or 0.0),
            price_stoplimit=float(row.get("price_stoplimit", 0.0) or 0.0),
            sl=float(row.get("sl", 0.0) or 0.0),
            tp=float(row.get("tp", 0.0) or 0.0),
            setup_at=row.get("setup_at"),
            expiration_at=row.get("expiration_at"),
            magic=int(row.get("magic", 0) or 0),
            position_ticket=(
                int(position_ticket) if position_ticket not in {None, ""} else None
            ),
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
        require_mutation_binding: bool = False,
        mt5_module: Any | None = None,
    ) -> None:
        self.path = path
        self.login = login
        self.password = password
        self.server = server
        self.timeout_ms = timeout_ms
        self.portable = portable
        self.require_mutation_binding = bool(require_mutation_binding)
        self._mt5 = mt5_module
        self._initialized = False

    def load_account_snapshot(self) -> AccountSnapshot:
        mt5 = self._ensure_initialized()
        account_info = self._call_mt5(lambda module: module.account_info(), retry_on_none=True)
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
        tick = self._call_mt5(lambda module: module.symbol_info_tick(symbol), retry_on_none=True)
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
        terminal_info = self._call_mt5(lambda module: module.terminal_info(), retry_on_none=True)
        if terminal_info is None:
            raise RuntimeError(f"MT5 terminal_info() failed: {mt5.last_error()}")
        account_info = self._call_mt5(lambda module: module.account_info(), retry_on_none=True)
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

    def load_account_fingerprint(self) -> AccountFingerprintSnapshot:
        mt5 = self._ensure_initialized()
        account_info = self._call_mt5(lambda module: module.account_info(), retry_on_none=True)
        if account_info is None:
            raise RuntimeError(f"MT5 account_info() failed: {mt5.last_error()}")
        server = str(getattr(account_info, "server", "") or "")
        broker = str(getattr(account_info, "company", "") or "")
        return AccountFingerprintSnapshot(
            login=str(getattr(account_info, "login", "") or ""),
            server=server,
            broker=broker,
            is_live=self._account_trade_mode_is_live(
                mt5=mt5,
                account_info=account_info,
                server=server,
                broker=broker,
            ),
            margin_mode=canonical_account_margin_mode(
                getattr(account_info, "margin_mode", None), mt5_module=mt5
            ),
        )

    def _mutation_binding_error(
        self,
        mt5: Any,
        binding: MutationAccountBinding | None,
    ) -> str | None:
        """Verify terminal/account identity immediately before ``order_send``.

        This intentionally uses direct, single-attempt MT5 reads.  Reconnecting
        here could silently bind a different terminal/account between the
        lifecycle fence and the broker mutation.
        """

        if binding is None:
            return (
                "broker mutation is missing its immutable account binding"
                if self.require_mutation_binding
                else None
            )
        if not isinstance(binding, MutationAccountBinding):
            return "broker mutation account binding has an invalid type"

        expected_login = str(binding.login or "").strip()
        expected_server = str(binding.server or "").strip()
        expected_scope = str(binding.account_scope or "").strip().lower()
        expected_margin_mode = canonical_account_margin_mode(binding.margin_mode)
        if not expected_login or not expected_server:
            return "broker mutation account binding is incomplete"
        if expected_scope not in {"demo", "live"}:
            return "broker mutation account scope is invalid"
        if expected_margin_mode != "HEDGING":
            return "broker mutation requires a HEDGING account"

        if self.require_mutation_binding:
            if not str(self.path or "").strip():
                return "broker mutation requires an explicit MT5 terminal path"
            if self.login is None or not str(self.server or "").strip():
                return "broker mutation requires explicit MT5 login and server"
            if str(self.login) != expected_login or str(self.server) != expected_server:
                return "broker mutation binding differs from configured MT5 account"
            if not str(binding.terminal_path or "").strip() or not str(
                binding.terminal_data_path or ""
            ).strip():
                return "broker mutation requires an exact terminal/data-path binding"

        expected_terminal_path = str(binding.terminal_path or "").strip()
        expected_data_path = str(binding.terminal_data_path or "").strip()
        terminal_info = None
        if expected_terminal_path or expected_data_path or self.path:
            try:
                terminal_info = mt5.terminal_info()
            except Exception as exc:
                return f"terminal identity check failed before broker mutation: {exc}"
            if terminal_info is None:
                return "terminal identity is unavailable before broker mutation"

        # Keep account_info as the final MT5 read before order_send.  It narrows
        # the remaining external account-switch race to the unavoidable call
        # boundary between this check and the single broker mutation.
        try:
            account_info = mt5.account_info()
        except Exception as exc:
            return f"account identity check failed before broker mutation: {exc}"
        if account_info is None:
            return "account identity is unavailable before broker mutation"

        actual_login = str(getattr(account_info, "login", "") or "")
        actual_server = str(getattr(account_info, "server", "") or "")
        actual_broker = str(getattr(account_info, "company", "") or "")
        actual_scope_flag = self._account_trade_mode_is_live(
            mt5=mt5,
            account_info=account_info,
            server=actual_server,
            broker=actual_broker,
        )
        actual_scope = (
            "live" if actual_scope_flag is True else "demo" if actual_scope_flag is False else ""
        )
        actual_margin_mode = canonical_account_margin_mode(
            getattr(account_info, "margin_mode", None), mt5_module=mt5
        )
        if actual_login != expected_login:
            return "MT5 login changed immediately before broker mutation"
        if actual_server != expected_server:
            return "MT5 server changed immediately before broker mutation"
        if binding.broker and actual_broker != str(binding.broker):
            return "MT5 broker changed immediately before broker mutation"
        if actual_scope != expected_scope:
            return "MT5 demo/live scope changed immediately before broker mutation"
        if actual_margin_mode != expected_margin_mode:
            return "MT5 account margin mode changed immediately before broker mutation"

        if terminal_info is not None:
            actual_terminal_path = str(getattr(terminal_info, "path", "") or "")
            actual_data_path = str(getattr(terminal_info, "data_path", "") or "")
            if self.path and _terminal_install_path_text(actual_terminal_path) != _terminal_install_path_text(
                self.path
            ):
                return "active MT5 installation differs from configured terminal executable"
            if expected_terminal_path and _canonical_path_text(actual_terminal_path) != _canonical_path_text(
                expected_terminal_path
            ):
                return "MT5 terminal path changed immediately before broker mutation"
            if expected_data_path and _canonical_path_text(actual_data_path) != _canonical_path_text(
                expected_data_path
            ):
                return "MT5 terminal data path changed immediately before broker mutation"
        return None

    def load_available_symbols(self) -> list[str]:
        mt5 = self._ensure_initialized()
        symbols = self._call_mt5(lambda module: module.symbols_get(), retry_on_none=True)
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
        margin = self._call_mt5(
            lambda module: module.order_calc_margin(mt5_order_type, symbol, volume, price_to_use),
            retry_on_none=True,
        )
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
        result = self._call_mt5(lambda module: module.order_check(order_request), retry_on_none=True)
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
            return OrderSendResult(
                accepted=False,
                detail="symbol missing",
                retcode=None,
                execution_status="REJECTED",
            )
        symbol_info = self._prepare_symbol(symbol_name)
        trade_request = self._build_trade_request(mt5, symbol_info, request)
        binding_error = self._mutation_binding_error(
            mt5, request.get("_mutation_binding")
        )
        if binding_error:
            return OrderSendResult(
                accepted=False,
                detail=binding_error,
                retcode=None,
                execution_status="REJECTED",
            )
        try:
            # Broker mutations are intentionally single-attempt.  Retrying a
            # lost IPC response could duplicate an order already accepted by
            # the terminal; the caller must reconcile UNKNOWN from broker state.
            result = mt5.order_send(trade_request)
        except Exception as exc:
            return OrderSendResult(
                accepted=False,
                detail=f"order_send raised; broker outcome unknown: {exc}",
                retcode=None,
                execution_status="UNKNOWN",
                outcome_unknown=True,
            )
        if result is None:
            return OrderSendResult(
                accepted=False,
                detail=f"order_send returned no result; broker outcome unknown: {mt5.last_error()}",
                retcode=None,
                execution_status="UNKNOWN",
                outcome_unknown=True,
            )
        raw_retcode = getattr(result, "retcode", None)
        try:
            retcode = int(raw_retcode) if raw_retcode is not None else None
        except (TypeError, ValueError):
            retcode = None
        done_code = int(getattr(mt5, "TRADE_RETCODE_DONE", 10009))
        placed_code = int(getattr(mt5, "TRADE_RETCODE_PLACED", 10008))
        partial_code = int(getattr(mt5, "TRADE_RETCODE_DONE_PARTIAL", 10010))
        execution_status = {
            done_code: "FILLED",
            placed_code: "PLACED",
            partial_code: "PARTIAL",
        }.get(retcode, "UNKNOWN" if retcode is None else "REJECTED")
        accepted = execution_status in {"FILLED", "PLACED", "PARTIAL"}
        return OrderSendResult(
            accepted=accepted,
            detail=str(
                getattr(result, "comment", "")
                or ("order_send accepted" if accepted else "order_send rejected")
            ),
            retcode=retcode,
            order=getattr(result, "order", None),
            deal=getattr(result, "deal", None),
            volume=float(getattr(result, "volume", 0.0) or 0.0),
            price=float(getattr(result, "price", 0.0) or 0.0),
            bid=float(getattr(result, "bid", 0.0) or 0.0),
            ask=float(getattr(result, "ask", 0.0) or 0.0),
            request_id=getattr(result, "request_id", None),
            retcode_external=getattr(result, "retcode_external", None),
            execution_status=execution_status,
            outcome_unknown=execution_status == "UNKNOWN",
        )

    def load_open_positions(self, *, symbol: str | None = None) -> list[OpenPositionSnapshot]:
        mt5 = self._ensure_initialized()
        rows = self._call_mt5(
            lambda module: module.positions_get(symbol=symbol) if symbol else module.positions_get(),
            retry_on_none=True,
        )
        if rows is None:
            raise RuntimeError(f"MT5 positions_get() failed: {mt5.last_error()}")
        buy_code = int(getattr(mt5, "POSITION_TYPE_BUY", 0))
        return [
            OpenPositionSnapshot(
                ticket=int(getattr(row, "ticket", 0) or 0),
                symbol=str(getattr(row, "symbol", "") or ""),
                side="buy" if int(getattr(row, "type", -1)) == buy_code else "sell",
                volume=float(getattr(row, "volume", 0.0) or 0.0),
                price_open=float(getattr(row, "price_open", 0.0) or 0.0),
                sl=float(getattr(row, "sl", 0.0) or 0.0),
                tp=float(getattr(row, "tp", 0.0) or 0.0),
                profit=float(getattr(row, "profit", 0.0) or 0.0),
                opened_at=self._format_epoch(getattr(row, "time", None)),
                magic=int(getattr(row, "magic", 0) or 0),
                comment=str(getattr(row, "comment", "") or ""),
                position_identifier=int(
                    getattr(row, "identifier", None)
                    or getattr(row, "ticket", 0)
                    or 0
                ),
            )
            for row in rows
        ]

    def load_open_orders(self, *, symbol: str | None = None) -> list[OpenOrderSnapshot]:
        """Load every active/pending order, failing closed on API ambiguity."""

        mt5 = self._ensure_initialized()
        rows = self._call_mt5(
            lambda module: module.orders_get(symbol=symbol) if symbol else module.orders_get(),
            retry_on_none=True,
        )
        if rows is None:
            raise RuntimeError(f"MT5 orders_get() failed: {mt5.last_error()}")
        return [
            OpenOrderSnapshot(
                ticket=int(getattr(row, "ticket", 0) or 0),
                symbol=str(getattr(row, "symbol", "") or ""),
                order_type=self._map_order_type(mt5, getattr(row, "type", None)),
                state=self._map_order_state(mt5, getattr(row, "state", None)),
                volume_initial=float(getattr(row, "volume_initial", 0.0) or 0.0),
                volume_current=float(getattr(row, "volume_current", 0.0) or 0.0),
                price_open=float(getattr(row, "price_open", 0.0) or 0.0),
                price_stoplimit=float(getattr(row, "price_stoplimit", 0.0) or 0.0),
                sl=float(getattr(row, "sl", 0.0) or 0.0),
                tp=float(getattr(row, "tp", 0.0) or 0.0),
                setup_at=self._format_epoch(getattr(row, "time_setup", None)),
                expiration_at=self._format_epoch(getattr(row, "time_expiration", None)),
                magic=int(getattr(row, "magic", 0) or 0),
                position_ticket=(
                    int(getattr(row, "position_id", 0) or 0) or None
                ),
            )
            for row in rows
        ]

    def find_open_position(
        self,
        *,
        position_ticket: int | None = None,
        position_identifier: int | None = None,
        symbol: str | None = None,
    ) -> OpenPositionSnapshot | None:
        return _find_position_snapshot(
            self.load_open_positions(symbol=symbol),
            position_ticket=position_ticket,
            position_identifier=position_identifier,
        )

    def modify_position_protection(
        self,
        position_ticket: int | None = None,
        *,
        position_identifier: int | None = None,
        sl: float | None = None,
        tp: float | None = None,
        mutation_binding: MutationAccountBinding | None = None,
    ) -> PositionProtectionResult:
        invalid = _validate_protection_request(
            position_ticket=position_ticket,
            position_identifier=position_identifier,
            sl=sl,
            tp=tp,
        )
        if invalid:
            return PositionProtectionResult(accepted=False, detail=invalid)

        position = self.find_open_position(
            position_ticket=position_ticket,
            position_identifier=position_identifier,
        )
        if position is None:
            return PositionProtectionResult(
                accepted=False,
                detail="open position not found",
                position_ticket=position_ticket,
                position_identifier=position_identifier,
            )

        mt5 = self._ensure_initialized()
        symbol_info = self._prepare_symbol(position.symbol)
        tolerance = _position_price_tolerance(symbol_info)
        try:
            desired_sl = _normalize_position_price(
                position.sl if sl is None else float(sl), symbol_info
            )
            desired_tp = _normalize_position_price(
                position.tp if tp is None else float(tp), symbol_info
            )
        except (ArithmeticError, TypeError, ValueError) as exc:
            return _protection_result(
                position,
                accepted=False,
                detail=str(exc),
                retcode=None,
                changed=False,
                postcondition_met=False,
            )
        if _protection_matches(
            position,
            sl=desired_sl,
            tp=desired_tp,
            tolerance=tolerance,
        ):
            return _protection_result(
                position,
                accepted=True,
                detail="position protection already matches requested values",
                retcode=None,
                changed=False,
                postcondition_met=True,
            )

        action_code = getattr(mt5, "TRADE_ACTION_SLTP", None)
        if action_code is None:
            return _protection_result(
                position,
                accepted=False,
                detail="MT5 module does not expose TRADE_ACTION_SLTP",
                retcode=None,
                changed=False,
                postcondition_met=False,
            )
        request = {
            "action": action_code,
            "symbol": position.symbol,
            "position": position.ticket,
            "sl": desired_sl,
            "tp": desired_tp,
        }
        binding_error = self._mutation_binding_error(mt5, mutation_binding)
        if binding_error:
            return _protection_result(
                position,
                accepted=False,
                detail=binding_error,
                retcode=None,
                changed=False,
                postcondition_met=False,
            )
        send_exception: Exception | None = None
        try:
            # SLTP is a broker mutation.  It must never use the automatic IPC
            # retry path because an absent response does not prove non-execution.
            result = mt5.order_send(request)
        except Exception as exc:
            result = None
            send_exception = exc
        send_error = (
            f"exception={send_exception}"
            if send_exception is not None
            else mt5.last_error() if result is None else None
        )
        stable_identifier = (
            position.position_identifier
            if position.position_identifier is not None
            else position.ticket
        )
        verification_error: str | None = None
        try:
            observed = self.find_open_position(position_identifier=stable_identifier)
        except Exception as exc:  # broker response must remain observable even if reconciliation fails
            observed = None
            verification_error = str(exc)
        postcondition_met = bool(
            observed
            and _protection_matches(
                observed,
                sl=desired_sl,
                tp=desired_tp,
                tolerance=tolerance,
            )
        )
        changed = bool(
            observed
            and not _protection_matches(
                observed,
                sl=position.sl,
                tp=position.tp,
                tolerance=tolerance,
            )
        )
        if result is None:
            detail = f"order_send SLTP returned no result; broker outcome unknown: {send_error}"
            if verification_error:
                detail += f"; postcondition verification failed: {verification_error}"
            return PositionProtectionResult(
                accepted=False,
                detail=detail,
                retcode=None,
                position_ticket=observed.ticket if observed else position.ticket,
                position_identifier=stable_identifier,
                sl=observed.sl if observed else None,
                tp=observed.tp if observed else None,
                changed=changed,
                postcondition_met=postcondition_met,
                outcome_unknown=True,
            )

        raw_retcode = getattr(result, "retcode", None)
        try:
            retcode = int(raw_retcode) if raw_retcode is not None else None
        except (TypeError, ValueError):
            retcode = None
        done_code = int(getattr(mt5, "TRADE_RETCODE_DONE", 10009))
        broker_accepted = retcode == done_code
        comment = str(getattr(result, "comment", "") or "")
        order = getattr(result, "order", None)
        deal = getattr(result, "deal", None)
        request_id = getattr(result, "request_id", None)
        retcode_external = getattr(result, "retcode_external", None)
        if broker_accepted and postcondition_met:
            detail = comment or "position protection updated"
        elif broker_accepted:
            detail = "broker accepted protection request but postcondition was not met"
        elif postcondition_met:
            detail = (
                (comment + "; ") if comment else ""
            ) + "broker retcode rejected although requested protection is observable"
        else:
            detail = comment or "broker rejected position protection request"
        if verification_error:
            detail += f"; postcondition verification failed: {verification_error}"
        if observed is None:
            return PositionProtectionResult(
                accepted=False,
                detail=detail,
                retcode=retcode,
                position_ticket=position.ticket,
                position_identifier=stable_identifier,
                sl=None,
                tp=None,
                changed=False,
                postcondition_met=False,
                order=order,
                deal=deal,
                request_id=request_id,
                retcode_external=retcode_external,
            )
        return _protection_result(
            observed,
            accepted=broker_accepted and postcondition_met,
            detail=detail,
            retcode=retcode,
            changed=changed,
            postcondition_met=postcondition_met,
            order=order,
            deal=deal,
            request_id=request_id,
            retcode_external=retcode_external,
        )

    def load_deals(self, *, since: datetime, symbol: str | None = None) -> list[DealSnapshot]:
        mt5 = self._ensure_initialized()
        start = since if since.tzinfo else since.replace(tzinfo=timezone.utc)
        rows = self._call_mt5(
            lambda module: module.history_deals_get(start, datetime.now(timezone.utc)),
            retry_on_none=True,
        )
        if rows is None:
            raise RuntimeError(f"MT5 history_deals_get() failed: {mt5.last_error()}")
        buy_code = int(getattr(mt5, "DEAL_TYPE_BUY", 0))
        entry_names = {
            int(getattr(mt5, "DEAL_ENTRY_IN", 0)): "in",
            int(getattr(mt5, "DEAL_ENTRY_OUT", 1)): "out",
            int(getattr(mt5, "DEAL_ENTRY_INOUT", 2)): "inout",
            int(getattr(mt5, "DEAL_ENTRY_OUT_BY", 3)): "out_by",
        }
        reason_names = {
            int(getattr(mt5, "DEAL_REASON_CLIENT", 0)): "manual_desktop",
            int(getattr(mt5, "DEAL_REASON_MOBILE", 1)): "manual_mobile",
            int(getattr(mt5, "DEAL_REASON_WEB", 2)): "manual_web",
            int(getattr(mt5, "DEAL_REASON_EXPERT", 3)): "expert",
            int(getattr(mt5, "DEAL_REASON_SL", 4)): "stop_loss",
            int(getattr(mt5, "DEAL_REASON_TP", 5)): "take_profit",
            int(getattr(mt5, "DEAL_REASON_SO", 6)): "stop_out",
        }
        result: list[DealSnapshot] = []
        for row in rows:
            row_symbol = str(getattr(row, "symbol", "") or "")
            if symbol and row_symbol != symbol:
                continue
            raw_entry = int(getattr(row, "entry", -1))
            raw_reason = int(getattr(row, "reason", -1))
            result.append(
                DealSnapshot(
                    ticket=int(getattr(row, "ticket", 0) or 0),
                    position_ticket=int(getattr(row, "position_id", 0) or 0),
                    symbol=row_symbol,
                    side="buy" if int(getattr(row, "type", -1)) == buy_code else "sell",
                    entry=entry_names.get(raw_entry, str(raw_entry)),
                    volume=float(getattr(row, "volume", 0.0) or 0.0),
                    price=float(getattr(row, "price", 0.0) or 0.0),
                    profit=float(getattr(row, "profit", 0.0) or 0.0),
                    commission=float(getattr(row, "commission", 0.0) or 0.0),
                    swap=float(getattr(row, "swap", 0.0) or 0.0),
                    reason=reason_names.get(raw_reason, str(raw_reason)),
                    occurred_at=self._format_epoch(getattr(row, "time", None)),
                    magic=int(getattr(row, "magic", 0) or 0),
                    comment=str(getattr(row, "comment", "") or ""),
                    fee=float(getattr(row, "fee", 0.0) or 0.0),
                )
            )
        return result

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
        symbol_info = self._call_mt5(lambda module: module.symbol_info(symbol), retry_on_none=True)
        if symbol_info is None:
            raise RuntimeError(f"MT5 symbol_info({symbol}) failed: {mt5.last_error()}")
        visible = bool(getattr(symbol_info, "visible", False))
        if not visible and not self._call_mt5(lambda module: module.symbol_select(symbol, True), retry_on_false=True):
            raise RuntimeError(f"MT5 symbol_select({symbol}, True) failed: {mt5.last_error()}")
        if not visible:
            symbol_info = self._call_mt5(lambda module: module.symbol_info(symbol), retry_on_none=True)
            if symbol_info is None:
                raise RuntimeError(f"MT5 symbol_info({symbol}) failed after select: {mt5.last_error()}")
        return symbol_info

    def _call_mt5(
        self,
        operation,
        *,
        retry_on_none: bool = False,
        retry_on_false: bool = False,
    ):
        mt5 = self._ensure_initialized()
        result = operation(mt5)
        if not self._should_retry_ipc_failure(
            mt5,
            result,
            retry_on_none=retry_on_none,
            retry_on_false=retry_on_false,
        ):
            return result
        self._reset_connection(mt5)
        mt5 = self._ensure_initialized()
        return operation(mt5)

    def _should_retry_ipc_failure(
        self,
        mt5,
        result,
        *,
        retry_on_none: bool,
        retry_on_false: bool,
    ) -> bool:
        failed = (retry_on_none and result is None) or (retry_on_false and result is False)
        return failed and self._is_ipc_error(mt5.last_error())

    def _reset_connection(self, mt5) -> None:
        with contextlib.suppress(Exception):
            mt5.shutdown()
        self._initialized = False

    @staticmethod
    def _is_ipc_error(error: Any) -> bool:
        if isinstance(error, tuple) and len(error) >= 2:
            message = str(error[1] or "")
        else:
            message = str(error or "")
        return "no ipc connection" in message.lower()

    def _build_trade_request(self, mt5, symbol_info, request: dict) -> dict[str, Any]:
        action_raw = str(request.get("action", "open") or "open").lower()
        order_type_raw = str(request.get("order_type", "buy") or "buy").lower()
        price = float(request.get("price", 0.0) or 0.0)
        if price <= 0:
            price = self._market_price(mt5, getattr(symbol_info, "name", ""), order_type_raw)

        trade_request: dict[str, Any] = {
            "action": getattr(mt5, "TRADE_ACTION_REMOVE") if action_raw == "cancel_pending" else getattr(mt5, "TRADE_ACTION_DEAL"),
            "symbol": getattr(symbol_info, "name", ""),
            "deviation": int(request.get("deviation", 20) or 20),
            "magic": int(request.get("magic", 234000) or 234000),
            "comment": str(request.get("comment", "bot-ea preflight") or "bot-ea preflight"),
            "type_time": getattr(mt5, "ORDER_TIME_GTC"),
        }
        if action_raw == "cancel_pending":
            trade_request["order"] = int(request.get("order_ticket") or request.get("order") or 0)
            return trade_request

        trade_request["volume"] = float(request.get("volume", 0.0) or 0.0)
        trade_request["type"] = self._resolve_order_type(mt5, order_type_raw)
        trade_request["type_filling"] = self._resolve_filling_type(mt5, symbol_info)
        if request.get("position_ticket") is not None or request.get("position") is not None:
            trade_request["position"] = int(request.get("position_ticket") or request.get("position"))

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

    @staticmethod
    def _map_order_type(mt5: Any, value: Any) -> str:
        names = (
            ("ORDER_TYPE_BUY", "buy"),
            ("ORDER_TYPE_SELL", "sell"),
            ("ORDER_TYPE_BUY_LIMIT", "buy_limit"),
            ("ORDER_TYPE_SELL_LIMIT", "sell_limit"),
            ("ORDER_TYPE_BUY_STOP", "buy_stop"),
            ("ORDER_TYPE_SELL_STOP", "sell_stop"),
            ("ORDER_TYPE_BUY_STOP_LIMIT", "buy_stop_limit"),
            ("ORDER_TYPE_SELL_STOP_LIMIT", "sell_stop_limit"),
            ("ORDER_TYPE_CLOSE_BY", "close_by"),
        )
        for constant_name, label in names:
            constant = getattr(mt5, constant_name, None)
            if constant is not None and value == constant:
                return label
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return "unknown"
        return {
            0: "buy",
            1: "sell",
            2: "buy_limit",
            3: "sell_limit",
            4: "buy_stop",
            5: "sell_stop",
            6: "buy_stop_limit",
            7: "sell_stop_limit",
            8: "close_by",
        }.get(numeric, f"unknown_{numeric}")

    @staticmethod
    def _map_order_state(mt5: Any, value: Any) -> str:
        names = (
            ("ORDER_STATE_STARTED", "started"),
            ("ORDER_STATE_PLACED", "placed"),
            ("ORDER_STATE_CANCELED", "canceled"),
            ("ORDER_STATE_PARTIAL", "partial"),
            ("ORDER_STATE_FILLED", "filled"),
            ("ORDER_STATE_REJECTED", "rejected"),
            ("ORDER_STATE_EXPIRED", "expired"),
            ("ORDER_STATE_REQUEST_ADD", "request_add"),
            ("ORDER_STATE_REQUEST_MODIFY", "request_modify"),
            ("ORDER_STATE_REQUEST_CANCEL", "request_cancel"),
        )
        for constant_name, label in names:
            constant = getattr(mt5, constant_name, None)
            if constant is not None and value == constant:
                return label
        try:
            numeric = int(value)
        except (TypeError, ValueError):
            return "unknown"
        return {
            0: "started",
            1: "placed",
            2: "canceled",
            3: "partial",
            4: "filled",
            5: "rejected",
            6: "expired",
            7: "request_add",
            8: "request_modify",
            9: "request_cancel",
        }.get(numeric, f"unknown_{numeric}")

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
        tick = self._call_mt5(lambda module: module.symbol_info_tick(symbol), retry_on_none=True)
        if tick is None:
            raise RuntimeError(f"MT5 symbol_info_tick({symbol}) failed: {mt5.last_error()}")
        if order_type == "sell":
            return float(getattr(tick, "bid", 0.0) or 0.0)
        return float(getattr(tick, "ask", 0.0) or 0.0)

    @staticmethod
    def _infer_is_live(*, server: str, broker: str) -> bool | None:
        haystack = " ".join([server, broker]).lower()
        if not haystack.strip():
            return None
        if any(keyword in haystack for keyword in ("demo", "test", "trial", "practice")):
            return False
        return True

    @classmethod
    def _account_trade_mode_is_live(
        cls,
        *,
        mt5,
        account_info,
        server: str,
        broker: str,
    ) -> bool | None:
        """Prefer MT5's account trade mode over broker/server naming heuristics."""

        trade_mode = getattr(account_info, "trade_mode", None)
        if trade_mode is not None:
            real_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", None)
            demo_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", None)
            contest_mode = getattr(mt5, "ACCOUNT_TRADE_MODE_CONTEST", None)
            if real_mode is not None and trade_mode == real_mode:
                return True
            if trade_mode in {mode for mode in (demo_mode, contest_mode) if mode is not None}:
                return False
        return cls._infer_is_live(server=server, broker=broker)
