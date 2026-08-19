from __future__ import annotations

from dataclasses import dataclass
from math import floor, isfinite


@dataclass(frozen=True, slots=True)
class AdaptiveRiskConfig:
    risk_fraction: float = 0.03
    volume_min: float = 0.01
    volume_max: float = 50.0
    volume_step: float = 0.01
    maximum_margin_fraction: float = 0.20
    minimum_lot_risk_cap_fraction: float = 0.0
    soft_drawdown_fraction: float = 0.10
    medium_drawdown_fraction: float = 0.15
    hard_drawdown_fraction: float = 0.25
    soft_risk_multiplier: float = 0.75
    medium_risk_multiplier: float = 0.50

    def __post_init__(self) -> None:
        if not 0 < self.risk_fraction < 1:
            raise ValueError("risk fraction must be between zero and one")
        if self.volume_min <= 0 or self.volume_step <= 0:
            raise ValueError("minimum volume and volume step must be positive")
        if self.volume_max < self.volume_min:
            raise ValueError("maximum volume must be at least minimum volume")
        if not 0 < self.maximum_margin_fraction <= 1:
            raise ValueError("maximum margin fraction is invalid")
        if not 0 <= self.minimum_lot_risk_cap_fraction < 1:
            raise ValueError("minimum-lot risk cap fraction is invalid")
        if not (
            0
            < self.soft_drawdown_fraction
            < self.medium_drawdown_fraction
            < self.hard_drawdown_fraction
            < 1
        ):
            raise ValueError("drawdown thresholds must be strictly increasing")
        if not 0 < self.medium_risk_multiplier <= self.soft_risk_multiplier <= 1:
            raise ValueError("drawdown risk multipliers are invalid")


@dataclass(frozen=True, slots=True)
class AdaptiveRiskDecision:
    executable: bool
    volume: float
    reason: str
    equity: float
    high_water_equity: float
    drawdown_fraction: float
    configured_risk_fraction: float
    effective_risk_fraction: float
    risk_budget: float
    loss_per_lot: float
    projected_loss: float
    projected_risk_fraction: float
    margin_per_lot: float
    projected_margin: float
    raw_risk_volume: float
    raw_margin_volume: float


class AdaptiveCompoundSizer:
    """Risk-normalized, drawdown-aware sizing with strict broker-step flooring."""

    def __init__(self, config: AdaptiveRiskConfig | None = None) -> None:
        self.config = config or AdaptiveRiskConfig()

    def size(
        self,
        *,
        equity: float,
        high_water_equity: float,
        loss_per_lot: float,
        margin_per_lot: float,
    ) -> AdaptiveRiskDecision:
        values = (equity, high_water_equity, loss_per_lot, margin_per_lot)
        if not all(isfinite(value) for value in values):
            raise ValueError("risk sizing values must be finite")
        if equity <= 0 or high_water_equity <= 0:
            raise ValueError("equity and high-water equity must be positive")
        if loss_per_lot <= 0 or margin_per_lot < 0:
            raise ValueError("loss per lot must be positive and margin non-negative")
        high_water = max(high_water_equity, equity)
        drawdown = max(0.0, (high_water - equity) / high_water)
        effective_fraction = self._effective_risk_fraction(drawdown)
        risk_budget = equity * effective_fraction
        raw_risk_volume = risk_budget / loss_per_lot
        raw_margin_volume = (
            equity * self.config.maximum_margin_fraction / margin_per_lot
            if margin_per_lot > 0
            else self.config.volume_max
        )
        raw_volume = min(
            raw_risk_volume,
            raw_margin_volume,
            self.config.volume_max,
        )
        volume = self._floor_volume(raw_volume)
        reason = "RISK_SIZED"
        if drawdown >= self.config.hard_drawdown_fraction:
            volume = 0.0
            reason = "HARD_DRAWDOWN_PAUSE"
        elif volume < self.config.volume_min:
            minimum_lot_risk = loss_per_lot * self.config.volume_min / equity
            minimum_lot_margin = margin_per_lot * self.config.volume_min
            if (
                self.config.minimum_lot_risk_cap_fraction > 0
                and minimum_lot_risk
                <= self.config.minimum_lot_risk_cap_fraction
                and minimum_lot_margin
                <= equity * self.config.maximum_margin_fraction
            ):
                volume = self.config.volume_min
                reason = "MINIMUM_LOT_BRIDGE"
            else:
                volume = 0.0
                reason = "BELOW_MINIMUM_EXECUTABLE_VOLUME"
        projected_loss = loss_per_lot * volume
        projected_margin = margin_per_lot * volume
        return AdaptiveRiskDecision(
            executable=volume >= self.config.volume_min,
            volume=volume,
            reason=reason,
            equity=equity,
            high_water_equity=high_water,
            drawdown_fraction=drawdown,
            configured_risk_fraction=self.config.risk_fraction,
            effective_risk_fraction=effective_fraction,
            risk_budget=risk_budget,
            loss_per_lot=loss_per_lot,
            projected_loss=projected_loss,
            projected_risk_fraction=projected_loss / equity,
            margin_per_lot=margin_per_lot,
            projected_margin=projected_margin,
            raw_risk_volume=raw_risk_volume,
            raw_margin_volume=raw_margin_volume,
        )

    def _effective_risk_fraction(self, drawdown: float) -> float:
        if drawdown >= self.config.hard_drawdown_fraction:
            return 0.0
        if drawdown >= self.config.medium_drawdown_fraction:
            return self.config.risk_fraction * self.config.medium_risk_multiplier
        if drawdown >= self.config.soft_drawdown_fraction:
            return self.config.risk_fraction * self.config.soft_risk_multiplier
        return self.config.risk_fraction

    def _floor_volume(self, raw_volume: float) -> float:
        if raw_volume < self.config.volume_min:
            return 0.0
        steps = floor((raw_volume + 1e-12) / self.config.volume_step)
        value = min(steps * self.config.volume_step, self.config.volume_max)
        decimals = max(0, len(f"{self.config.volume_step:.10f}".rstrip("0").split(".")[-1]))
        return round(value, decimals)
