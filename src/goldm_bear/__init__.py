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
from .replay import BearReplay, BearReplayOutcome, BearReplayReport
from .candidate import (
    confluence_v1_config,
    confluence_v2_config,
    confluence_v3_config,
)
from .multitimeframe import (
    BearMultiTimeframeReplay,
    BearV4Config,
    BearV4Outcome,
    BearV4Report,
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
    "BearReplay",
    "BearReplayOutcome",
    "BearReplayReport",
    "confluence_v1_config",
    "confluence_v2_config",
    "confluence_v3_config",
    "BearMultiTimeframeReplay",
    "BearV4Config",
    "BearV4Outcome",
    "BearV4Report",
]
