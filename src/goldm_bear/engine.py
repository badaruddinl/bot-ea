"""Compatibility exports for the extracted pure Bear rule implementation."""

from gold_engine_core.rules.bear import (
    BearAction,
    BearBar,
    BearDecision,
    BearEngine,
    BearEngineConfig,
    BearExitAction,
    BearExitDecision,
    ShortPosition,
    _simple_rsi,
    _stochastic_stats,
)

__all__ = [
    "BearAction",
    "BearBar",
    "BearDecision",
    "BearEngine",
    "BearEngineConfig",
    "BearExitAction",
    "BearExitDecision",
    "ShortPosition",
    "_simple_rsi",
    "_stochastic_stats",
]
