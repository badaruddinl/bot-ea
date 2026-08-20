from __future__ import annotations

from dataclasses import replace

from .bear import BearEngineConfig


def confluence_v1_config(*, symbol: str = "GOLD.i#") -> BearEngineConfig:
    """Standalone bear candidate; intentionally imports no REVISED components."""

    return BearEngineConfig(
        symbol=symbol,
        confluence_enabled=True,
        confluence_min_votes=3,
        maximum_regime_drop_atr=4.0,
        fibonacci_lookback=48,
        fibonacci_min_impulse_atr=1.5,
        rsi_period=7,
        rsi_pullback_minimum=50.0,
        stochastic_period=14,
        stochastic_smoothing=3,
        stochastic_pullback_minimum=60.0,
        supply_lookback=48,
        supply_displacement_atr=1.0,
        momentum_body_atr=0.35,
        exhaustion_min_signals=2,
    )


def confluence_v2_config(*, symbol: str = "GOLD.i#") -> BearEngineConfig:
    """V1 plus independently implemented repeated-touch/acceptance evidence."""

    return replace(
        confluence_v1_config(symbol=symbol),
        range_confirmation_enabled=True,
        resistance_touch_lookback=12,
        resistance_touch_separation_bars=2,
        resistance_retreat_atr=0.25,
        resistance_min_touches=2,
        resistance_min_rejections=2,
        resistance_acceptance_closes=2,
    )


def confluence_v3_config(*, symbol: str = "GOLD.i#") -> BearEngineConfig:
    """V1 plus an independently implemented closed-H1 bearish trend gate."""

    return replace(
        confluence_v1_config(symbol=symbol),
        higher_timeframe_filter_enabled=True,
        h1_sma_period=20,
        h1_slope_lookback=5,
    )
