from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TradingStyle(str, Enum):
    SCALPING = "scalping"
    INTRADAY = "intraday"
    SWING = "swing"


class OperatingMode(str, Enum):
    RECOMMEND = "recommend"
    CAUTION = "caution"
    STRICT = "strict"


@dataclass(slots=True)
class AccountSnapshot:
    equity: float
    balance: float
    free_margin: float
    margin_level: float
    current_open_risk_pct: float = 0.0
    daily_realized_loss_pct: float = 0.0
    positions_total: int = 0


@dataclass(slots=True)
class SymbolSnapshot:
    name: str
    instrument_class: str
    risk_weight: float
    point: float
    tick_size: float
    tick_value: float
    volume_min: float
    volume_max: float
    volume_step: float
    spread_points: float
    stops_level_points: float
    freeze_level_points: float
    trade_mode: str = ""
    order_mode: str = ""
    execution_mode: str = ""
    filling_mode: str = ""
    quote_session_active: bool = True
    trade_session_active: bool = True
    trade_allowed: bool = True
    volatility_points: float | None = None


@dataclass(slots=True)
class RiskPolicy:
    base_risk_pct: float
    max_total_open_risk_pct: float
    daily_loss_limit_pct: float
    caution_risk_multiplier: float = 0.75
    strict_risk_multiplier: float = 0.50
    caution_spread_to_volatility_ratio: float = 0.10
    strict_spread_to_volatility_ratio: float = 0.20
    caution_margin_buffer_ratio: float = 0.35
    strict_margin_buffer_ratio: float = 0.20
    small_equity_threshold: float = 1_000.0
    caution_risk_weight: float = 1.20
    strict_risk_weight: float = 1.50


@dataclass(slots=True)
class SuitabilityAssessment:
    mode: OperatingMode
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PositionSizeRequest:
    account: AccountSnapshot
    symbol: SymbolSnapshot
    policy: RiskPolicy
    stop_distance_points: float
    force_symbol: bool = False
    requested_mode: OperatingMode | None = None


@dataclass(slots=True)
class PositionSizeResult:
    accepted: bool
    mode: OperatingMode
    effective_risk_pct: float
    risk_cash_budget: float
    normalized_volume: float
    estimated_loss_cash: float
    stop_distance_points: float
    rejection_reason: str | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class ExecutionGateResult:
    allowed: bool
    checks: list[GateCheck] = field(default_factory=list)


@dataclass(slots=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float
    tick_volume: float = 0.0
    spread_points: float = 0.0

    @property
    def range_points(self) -> float:
        return self.high - self.low

    @property
    def body_points(self) -> float:
        return abs(self.close - self.open)
