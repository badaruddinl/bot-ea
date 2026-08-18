"""Standalone GOLDM_REVISED shadow engine.

The package intentionally has no dependency on ``goldm_signal`` or
``goldm_bear``.  It is signal-only and never submits an MT5 order.
"""

from .engine import (
    ConfirmationMode,
    RevisedAction,
    RevisedBar,
    RevisedDecision,
    RevisedEngine,
    RevisedEngineConfig,
    RevisedSnapshot,
    RevisedState,
    RevisedSide,
)

__all__ = [
    "ConfirmationMode",
    "RevisedAction",
    "RevisedBar",
    "RevisedDecision",
    "RevisedEngine",
    "RevisedEngineConfig",
    "RevisedSnapshot",
    "RevisedState",
    "RevisedSide",
]
