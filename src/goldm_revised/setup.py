"""Compatibility exports for the extracted pure Revised setup rules."""

from gold_engine_core.rules.revised_setup import (
    RevisedConsumedSetup,
    RevisedDetectorState,
    RevisedM5Setup,
    RevisedSetupDetector,
    RevisedTermination,
    classify_m5_setup,
)

__all__ = [
    "RevisedConsumedSetup",
    "RevisedDetectorState",
    "RevisedM5Setup",
    "RevisedSetupDetector",
    "RevisedTermination",
    "classify_m5_setup",
]
