from __future__ import annotations

from dataclasses import dataclass, field
from math import isclose
from typing import Any

from ..config import GoldSymbolProfile


@dataclass(frozen=True, slots=True)
class RuntimeSymbolSpec:
    symbol: str
    point: float
    tick_size: float
    contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float
    stops_level_points: float
    profit_currency: str
    margin_currency: str

    @classmethod
    def from_mt5(cls, info: Any) -> "RuntimeSymbolSpec":
        return cls(
            symbol=str(getattr(info, "name", "") or ""),
            point=float(getattr(info, "point", 0.0) or 0.0),
            tick_size=float(getattr(info, "trade_tick_size", 0.0) or 0.0),
            contract_size=float(getattr(info, "trade_contract_size", 0.0) or 0.0),
            volume_min=float(getattr(info, "volume_min", 0.0) or 0.0),
            volume_max=float(getattr(info, "volume_max", 0.0) or 0.0),
            volume_step=float(getattr(info, "volume_step", 0.0) or 0.0),
            stops_level_points=float(getattr(info, "trade_stops_level", 0.0) or 0.0),
            profit_currency=str(getattr(info, "currency_profit", "") or ""),
            margin_currency=str(getattr(info, "currency_margin", "") or ""),
        )


@dataclass(slots=True)
class SymbolSpecCheck:
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def check_symbol_spec(profile: GoldSymbolProfile, runtime: RuntimeSymbolSpec) -> SymbolSpecCheck:
    errors: list[str] = []
    warnings: list[str] = []

    expected_numbers = (
        ("tick_size", runtime.tick_size, profile.price_increment),
        ("contract_size", runtime.contract_size, profile.contract_size_oz),
        ("volume_min", runtime.volume_min, profile.volume_min),
        ("volume_max", runtime.volume_max, profile.volume_max),
        ("stops_level_points", runtime.stops_level_points, profile.stops_level_points),
    )
    if runtime.symbol != profile.symbol:
        errors.append(f"symbol mismatch: expected {profile.symbol}, got {runtime.symbol or '<empty>'}")
    for name, actual, expected in expected_numbers:
        if not isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9):
            errors.append(f"{name} mismatch: expected {expected:g}, got {actual:g}")
    if runtime.profit_currency.upper() != profile.profit_currency:
        errors.append(
            f"profit currency mismatch: expected {profile.profit_currency}, got {runtime.profit_currency or '<empty>'}"
        )
    if runtime.margin_currency.upper() != profile.margin_currency:
        errors.append(
            f"margin currency mismatch: expected {profile.margin_currency}, got {runtime.margin_currency or '<empty>'}"
        )
    if runtime.volume_step <= 0:
        errors.append("broker volume_step is unavailable or invalid")
    elif profile.volume_step is None:
        warnings.append(f"volume_step learned from MT5 at runtime: {runtime.volume_step:g}")
    if not isclose(runtime.point, profile.price_increment, rel_tol=1e-9, abs_tol=1e-9):
        warnings.append(
            f"MT5 point ({runtime.point:g}) differs from minimum price fluctuation ({profile.price_increment:g})"
        )
    return SymbolSpecCheck(passed=not errors, errors=errors, warnings=warnings)
