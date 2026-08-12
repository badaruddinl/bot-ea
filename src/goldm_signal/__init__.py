"""GoldM Sniper signal-only service.

This package deliberately exposes market analysis and notification primitives only.
It does not contain an order-send API.
"""

from .config import GoldSymbolProfile, SignalPolicy, gold_i_profile

__all__ = ["GoldSymbolProfile", "SignalPolicy", "gold_i_profile"]
