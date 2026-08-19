from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class GoldInstrumentProfile:
    profile_id: str
    symbol: str
    contract_size_oz: float
    volume_min: float
    volume_step: float
    volume_max: float
    price_tick: float
    spread_floor_usd: float
    low_lot: float
    high_lot: float
    partial_lot: float
    step_up_balance_usd: float

    def __post_init__(self) -> None:
        positive = (
            self.contract_size_oz,
            self.volume_min,
            self.volume_step,
            self.volume_max,
            self.price_tick,
            self.low_lot,
            self.high_lot,
            self.partial_lot,
            self.step_up_balance_usd,
        )
        if not self.profile_id or not self.symbol:
            raise ValueError("profile id and symbol are required")
        if any(value <= 0.0 for value in positive):
            raise ValueError("instrument profile values must be positive")
        if self.spread_floor_usd < 0.0:
            raise ValueError("spread floor cannot be negative")
        if self.low_lot > self.high_lot:
            raise ValueError("low lot cannot exceed high lot")
        if not isclose(self.partial_lot * 2.0, self.high_lot, abs_tol=1e-12):
            raise ValueError("high lot must split into two equal partial lots")
        for lot in (self.low_lot, self.high_lot, self.partial_lot):
            if not self.is_executable_lot(lot):
                raise ValueError(f"lot is not executable for profile: {lot}")

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "GoldInstrumentProfile":
        instrument = payload["instrument"]
        sizing = payload["sizing"]
        return cls(
            profile_id=str(payload["profile_id"]),
            symbol=str(instrument["symbol"]),
            contract_size_oz=float(instrument["contract_size_oz"]),
            volume_min=float(instrument["volume_min"]),
            volume_step=float(instrument["volume_step"]),
            volume_max=float(instrument["volume_max"]),
            price_tick=float(instrument["price_tick"]),
            spread_floor_usd=float(instrument["spread_floor_usd"]),
            low_lot=float(sizing["low_lot"]),
            high_lot=float(sizing["high_lot"]),
            partial_lot=float(sizing["partial_lot"]),
            step_up_balance_usd=float(sizing["step_up_balance_usd"]),
        )

    def exposure_ounces(self, lot: float) -> float:
        return self.contract_size_oz * lot

    def lot_for_exposure(self, exposure_ounces: float) -> float:
        if exposure_ounces <= 0.0:
            raise ValueError("exposure must be positive")
        return exposure_ounces / self.contract_size_oz

    def is_executable_lot(self, lot: float) -> bool:
        if lot + 1e-12 < self.volume_min or lot > self.volume_max + 1e-12:
            return False
        steps = round(lot / self.volume_step)
        return isclose(steps * self.volume_step, lot, abs_tol=1e-12)

    def validate_mt5_symbol_info(self, info: Any) -> tuple[str, ...]:
        if info is None:
            return (f"symbol unavailable: {self.symbol}",)
        errors: list[str] = []
        expected = {
            "name": self.symbol,
            "trade_contract_size": self.contract_size_oz,
            "volume_min": self.volume_min,
            "volume_step": self.volume_step,
            "point": self.price_tick,
            "trade_tick_size": self.price_tick,
        }
        for field, wanted in expected.items():
            actual = getattr(info, field, None)
            if isinstance(wanted, str):
                matches = str(actual) == wanted
            else:
                matches = actual is not None and isclose(
                    float(actual),
                    float(wanted),
                    rel_tol=0.0,
                    abs_tol=1e-12,
                )
            if not matches:
                errors.append(f"{field}: expected {wanted}, got {actual}")
        actual_max = getattr(info, "volume_max", None)
        if actual_max is None or float(actual_max) + 1e-12 < self.high_lot:
            errors.append(
                f"volume_max: requires at least {self.high_lot}, got {actual_max}"
            )
        return tuple(errors)

