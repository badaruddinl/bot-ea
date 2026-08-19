from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "simulate-goldm-combined-portfolio.py"


def _module():
    spec = importlib.util.spec_from_file_location("goldm_combined_portfolio", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_shared_floating_profit_uses_one_market_price_for_both_sides() -> None:
    module = _module()
    buy = {"side": "BUY", "entry": 100.0, "lot": 0.02}
    sell = {"side": "SELL", "entry": 100.0, "lot": 0.02}

    assert module._floating_profit(buy, 101.0, 100.0) == 2.0
    assert module._floating_profit(sell, 99.0, 100.0) == 2.0
    assert (
        module._floating_profit(buy, 101.0, 100.0)
        + module._floating_profit(sell, 101.0, 100.0)
        == 0.0
    )
