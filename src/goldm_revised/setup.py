"""Compatibility exports for the extracted pure Revised setup rules."""

from gold_engine_core.rules.revised_setup import (
    RevisedM5Setup,
    RevisedSetupDetector,
    classify_m5_setup,
)

__all__ = ["RevisedM5Setup", "RevisedSetupDetector", "classify_m5_setup"]
