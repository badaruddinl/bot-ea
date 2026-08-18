"""Standalone bearish GOLD signal engine.

This package intentionally has no dependency on the production ``goldm_signal``
strategy.  It is a separate research implementation built from OHLC bars.
"""

from .engine import (
    BearAction,
    BearBar,
    BearDecision,
    BearEngine,
    BearEngineConfig,
    BearExitAction,
    BearExitDecision,
    ShortPosition,
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
]
