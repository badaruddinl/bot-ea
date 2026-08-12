from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True, slots=True)
class SessionWindow:
    start: time
    end: time

    def contains(self, value: time) -> bool:
        return self.start <= value <= self.end


@dataclass(frozen=True, slots=True)
class GoldSymbolProfile:
    symbol: str
    instrument_name: str
    asset_class: str
    contract_size_oz: float
    volume_min: float
    volume_max: float
    price_increment: float
    stops_level_points: float
    profit_currency: str
    margin_currency: str
    leverage: int
    hedged_margin_discount_pct: float
    spread_as_low_as_price: float
    quote_window: SessionWindow
    trade_window: SessionWindow
    server_timezone: str | None = None
    volume_step: float | None = None


@dataclass(frozen=True, slots=True)
class SignalPolicy:
    required_timeframes: tuple[str, ...] = ("D1", "H4", "H1", "M15", "M5")
    max_spread_to_atr: float = 0.10
    max_tick_age_seconds: int = 120
    max_retest_bars: int = 10
    setup_score_a_plus: int = 93
    minimum_projected_r: float = 3.0
    minimum_p_1r: float = 0.68
    minimum_p_2r: float = 0.52
    minimum_p_3r: float = 0.35
    minimum_expected_r: float = 0.40
    default_research_risk_pct: float = 0.005
    normal_maximum_risk_pct: float = 0.01
    absolute_manual_risk_cap_pct: float = 0.02


def gold_i_profile() -> GoldSymbolProfile:
    """Broker facts supplied for GOLD.i#.

    The broker did not supply a server timezone or volume step, so those fields
    remain unknown until verified from ``symbol_info`` at runtime.
    """

    return GoldSymbolProfile(
        symbol="GOLD.i#",
        instrument_name="GOLD",
        asset_class="Precious Metals",
        contract_size_oz=100.0,
        volume_min=0.01,
        volume_max=50.0,
        price_increment=0.01,
        stops_level_points=0.0,
        profit_currency="USD",
        margin_currency="USD",
        leverage=1000,
        hedged_margin_discount_pct=100.0,
        spread_as_low_as_price=0.2,
        quote_window=SessionWindow(time(1, 0), time(23, 59)),
        trade_window=SessionWindow(time(1, 2), time(23, 58)),
    )
