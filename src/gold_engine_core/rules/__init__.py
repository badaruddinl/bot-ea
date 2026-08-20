"""Pure strategy rules shared by replay, live reference feeders, and MQL5 parity."""

from .bear import (
    BearAction,
    BearBar,
    BearDecision,
    BearEngine,
    BearEngineConfig,
    BearExitAction,
    BearExitDecision,
    ShortPosition,
)
from .bear_candidate import confluence_v1_config, confluence_v2_config, confluence_v3_config
from .bear_multitimeframe import (
    BearMultiTimeframeReplay,
    BearV4Config,
    BearV4Outcome,
    BearV4Report,
)
from .revised import (
    ConfirmationMode,
    RevisedAction,
    RevisedBar,
    RevisedDecision,
    RevisedEngine,
    RevisedEngineConfig,
    RevisedSide,
    RevisedSnapshot,
    RevisedState,
)
from .revised_setup import RevisedM5Setup, RevisedSetupDetector, classify_m5_setup

__all__ = [
    "BearAction",
    "BearBar",
    "BearDecision",
    "BearEngine",
    "BearEngineConfig",
    "BearExitAction",
    "BearExitDecision",
    "BearMultiTimeframeReplay",
    "BearV4Config",
    "BearV4Outcome",
    "BearV4Report",
    "ConfirmationMode",
    "RevisedAction",
    "RevisedBar",
    "RevisedDecision",
    "RevisedEngine",
    "RevisedEngineConfig",
    "RevisedM5Setup",
    "RevisedSetupDetector",
    "RevisedSide",
    "RevisedSnapshot",
    "RevisedState",
    "ShortPosition",
    "classify_m5_setup",
    "confluence_v1_config",
    "confluence_v2_config",
    "confluence_v3_config",
]
