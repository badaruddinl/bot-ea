from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay-goldm-dual-tp.py"


def test_dual_tp_module_loads_and_declares_split_policies() -> None:
    spec = importlib.util.spec_from_file_location("goldm_dual_tp", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert "SPLIT_KEEP_STOP" in module.POLICIES
    assert "SPLIT_BE_AFTER_TP1" in module.POLICIES
