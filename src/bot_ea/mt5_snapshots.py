from __future__ import annotations

from collections.abc import Mapping

from .models import AccountSnapshot, SymbolSnapshot
from .symbol_policy import default_risk_weight, infer_instrument_class


def _read(source, key: str, default=None):
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)


def build_account_snapshot(account_info) -> AccountSnapshot:
    return AccountSnapshot(
        equity=float(_read(account_info, "equity", 0.0) or 0.0),
        balance=float(_read(account_info, "balance", 0.0) or 0.0),
        free_margin=float(_read(account_info, "margin_free", 0.0) or 0.0),
        margin_level=float(_read(account_info, "margin_level", 0.0) or 0.0),
        trade_allowed=bool(_read(account_info, "trade_allowed", True)),
        trade_expert=bool(_read(account_info, "trade_expert", True)),
        current_open_risk_pct=0.0,
        daily_realized_loss_pct=0.0,
        positions_total=int(_read(account_info, "positions", 0) or 0),
    )


def build_symbol_snapshot(symbol_info, *, quote_session_active: bool, trade_session_active: bool, volatility_points: float | None = None) -> SymbolSnapshot:
    name = str(_read(symbol_info, "name", "") or "")
    instrument_class = infer_instrument_class(name)
    trade_mode = str(_read(symbol_info, "trade_mode", "") or "")
    trade_allowed = bool(_read(symbol_info, "visible", True))
    margin_initial = float(_read(symbol_info, "margin_initial", 0.0) or 0.0)
    margin_rate = margin_initial if 0.0 < margin_initial <= 1.0 else 0.0
    if trade_mode:
        trade_allowed = trade_allowed and trade_mode.lower() not in {"disabled", "closeonly"}
    return SymbolSnapshot(
        name=name,
        instrument_class=instrument_class,
        risk_weight=default_risk_weight(name),
        trade_mode=trade_mode,
        order_mode=str(_read(symbol_info, "order_mode", "") or ""),
        execution_mode=str(_read(symbol_info, "trade_exemode", "") or ""),
        filling_mode=str(_read(symbol_info, "filling_mode", "") or ""),
        point=float(_read(symbol_info, "point", 0.0) or 0.0),
        tick_size=float(_read(symbol_info, "trade_tick_size", 0.0) or 0.0),
        tick_value=float(_read(symbol_info, "trade_tick_value", 0.0) or 0.0),
        volume_min=float(_read(symbol_info, "volume_min", 0.0) or 0.0),
        volume_max=float(_read(symbol_info, "volume_max", 0.0) or 0.0),
        volume_step=float(_read(symbol_info, "volume_step", 0.0) or 0.0),
        spread_points=float(_read(symbol_info, "spread", 0.0) or 0.0),
        stops_level_points=float(_read(symbol_info, "trade_stops_level", 0.0) or 0.0),
        freeze_level_points=float(_read(symbol_info, "trade_freeze_level", 0.0) or 0.0),
        quote_session_active=quote_session_active,
        trade_session_active=trade_session_active,
        trade_allowed=trade_allowed,
        volatility_points=volatility_points,
        price=float(_read(symbol_info, "ask", 0.0) or _read(symbol_info, "bid", 0.0) or _read(symbol_info, "last", 0.0) or 0.0),
        bid=float(_read(symbol_info, "bid", 0.0) or 0.0),
        ask=float(_read(symbol_info, "ask", 0.0) or 0.0),
        contract_size=float(_read(symbol_info, "trade_contract_size", 0.0) or 0.0),
        margin_rate=margin_rate,
    )
