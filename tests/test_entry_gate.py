from __future__ import annotations

from pathlib import Path

import pytest

from gold_orchestrator.entry_gate import EntryGateController

FINGERPRINT = "a" * 64


def _session(root: Path, profile: str, *, authority: bool = True, session: str = "s1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{profile}.entry-session").write_text(
        f"1|{profile}|{FINGERPRINT}|123|{session}|{'ENABLED' if authority else 'DISABLED'}\n",
        encoding="ascii",
    )


def test_missing_session_is_fail_closed(tmp_path: Path) -> None:
    status = EntryGateController(tmp_path).status("GOLDI")
    assert not status.available
    assert not status.enabled


def test_admin_can_enable_and_disable_current_session(tmp_path: Path) -> None:
    _session(tmp_path, "GOLDM")
    controller = EntryGateController(tmp_path)

    assert controller.set_enabled("GOLDM", True, actor_id="321").enabled
    assert not controller.set_enabled("GOLDM", False, actor_id="321").enabled


def test_restart_session_invalidates_previous_enable(tmp_path: Path) -> None:
    _session(tmp_path, "GOLDI", session="first")
    controller = EntryGateController(tmp_path)
    assert controller.set_enabled("GOLDI", True, actor_id="321").enabled

    _session(tmp_path, "GOLDI", session="second")

    assert not controller.status("GOLDI").enabled


def test_disabled_order_authority_cannot_enable_entries(tmp_path: Path) -> None:
    _session(tmp_path, "GOLDM", authority=False)
    controller = EntryGateController(tmp_path)

    with pytest.raises(RuntimeError, match="order authority is disabled"):
        controller.set_enabled("GOLDM", True, actor_id="321")


def test_non_admin_actor_id_is_rejected(tmp_path: Path) -> None:
    _session(tmp_path, "GOLDI")
    controller = EntryGateController(tmp_path)

    with pytest.raises(ValueError, match="positive private chat ID"):
        controller.set_enabled("GOLDI", True, actor_id="-999")
