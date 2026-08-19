from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay-goldm-revised-trailing.py"


def _module():
    spec = importlib.util.spec_from_file_location("goldm_revised_trailing", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_locked_r_uses_highest_completed_close_step() -> None:
    module = _module()
    policy = ((0.5, 0.0), (0.75, 0.1), (1.0, 0.25))

    assert module.locked_r_for_close(0.49, policy) is None
    assert module.locked_r_for_close(0.50, policy) == 0.0
    assert module.locked_r_for_close(0.80, policy) == 0.1
    assert module.locked_r_for_close(1.20, policy) == 0.25


def test_no_trail_policy_never_locks() -> None:
    module = _module()
    assert module.locked_r_for_close(10.0, ()) is None
