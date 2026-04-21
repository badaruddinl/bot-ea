from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bot_ea.operator_state import OperatorStateStore  # noqa: E402


FINGERPRINT = {
    "login": "123456",
    "server": "Demo-Server",
    "broker": "Broker Demo",
    "is_live": False,
}


def _store(tmp_path: Path) -> OperatorStateStore:
    return OperatorStateStore(tmp_path)


def test_runtime_state_round_trip_and_update(tmp_path: Path) -> None:
    store = _store(tmp_path)

    initial = store.load_runtime_state()
    assert initial["last_runtime_state"] == "stopped"
    assert initial["context_key"] == ""

    saved = store.save_runtime_state(
        {
            "active_account_fingerprint": dict(FINGERPRINT),
            "context_key": "broker_demo_demo_server_123456",
            "context_path": str((tmp_path / "ai_context" / "broker_demo_demo_server_123456").resolve()),
            "last_runtime_state": "ready",
        }
    )
    assert saved["active_account_fingerprint"]["login"] == "123456"
    assert saved["updated_at"]

    updated = store.update_runtime_state({"last_runtime_state": "halted"}, last_shutdown_reason="mt5_disconnect")
    assert updated["last_runtime_state"] == "halted"
    assert updated["last_shutdown_reason"] == "mt5_disconnect"

    raw = json.loads(store.runtime_state_path.read_text(encoding="utf-8"))
    assert raw["last_runtime_state"] == "halted"
    assert raw["last_shutdown_reason"] == "mt5_disconnect"


def test_last_session_round_trip_and_update(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()
    result = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)

    context_path = Path(result["binding"]["context_path"])
    initial = store.load_last_session(context_path=context_path)
    assert initial["account_fingerprint"]["login"] == "123456"
    assert initial["last_runtime_state"] == "stopped"

    updated = store.update_last_session(
        context_path=context_path,
        last_run_id="run-123",
        last_runtime_state="safe_halt",
        last_shutdown_reason="account_changed",
        last_symbol="XAUUSD",
    )
    assert updated["last_run_id"] == "run-123"
    assert updated["last_runtime_state"] == "safe_halt"
    assert updated["last_shutdown_reason"] == "account_changed"
    assert updated["last_symbol"] == "XAUUSD"
    assert updated["updated_at"]

    raw = json.loads((context_path / "memory" / "last_session.json").read_text(encoding="utf-8"))
    assert raw["last_run_id"] == "run-123"
    assert raw["last_runtime_state"] == "safe_halt"
    resume_prompt = (context_path / "resume" / "resume_prompt.md").read_text(encoding="utf-8")
    assert "## Last Session" in resume_prompt
    assert "run-123" in resume_prompt


def test_list_account_contexts_reports_mapped_existing_and_new_candidates(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()

    first = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)
    second = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT, create_new=True)

    store.update_last_session(
        context_path=Path(first["binding"]["context_path"]),
        last_runtime_state="ready",
        last_run_id="run-old",
    )
    store.update_last_session(
        context_path=Path(second["binding"]["context_path"]),
        last_runtime_state="running",
        last_run_id="run-new",
    )

    listing = store.list_account_contexts(settings=settings, fingerprint_payload=FINGERPRINT)
    keys = {entry["context_key"]: entry for entry in listing["available_contexts"]}

    assert listing["mapped_context_key"] == second["binding"]["context_key"]
    assert listing["default_context_key"] == second["binding"]["context_key"]
    assert first["binding"]["context_key"] in keys
    assert second["binding"]["context_key"] in keys
    assert keys[first["binding"]["context_key"]]["mapping_source"] == "existing"
    assert keys[second["binding"]["context_key"]]["mapping_source"] == "mapped"
    assert listing["new_context"]["mapping_source"] == "new_context"
    assert listing["new_context"]["context_key"] not in keys


def test_build_resume_state_can_select_existing_context(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()

    first = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)
    second = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT, create_new=True)

    rebound = store.build_resume_state(
        settings=settings,
        fingerprint_payload=FINGERPRINT,
        context_key=first["binding"]["context_key"],
    )

    assert second["binding"]["context_key"] != first["binding"]["context_key"]
    assert rebound["binding"]["context_key"] == first["binding"]["context_key"]
    assert rebound["binding"]["mapping_source"] == "existing"
    assert rebound["binding"]["created_now"] is False


def test_build_resume_state_uses_existing_base_context_when_mapping_missing(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()
    context_root = Path(settings.ai_context_root)
    existing_path = context_root / "broker_demo_demo_server_123456"
    existing_path.mkdir(parents=True, exist_ok=True)
    store.save_last_session(
        context_path=existing_path,
        payload={
            "account_fingerprint": dict(FINGERPRINT),
            "last_runtime_state": "stopped",
        },
    )

    result = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)

    assert result["binding"]["context_key"] == "broker_demo_demo_server_123456"
    assert result["binding"]["mapping_source"] == "existing"
    assert result["binding"]["created_now"] is False


def test_create_new_context_preserves_existing_resume_prompt_and_session(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()

    first = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)
    first_context_path = Path(first["binding"]["context_path"])
    first_resume_prompt = first_context_path / "resume" / "resume_prompt.md"
    first_resume_prompt.write_text("# Resume Prompt\n\n- catatan lama harus tetap ada.\n", encoding="utf-8")
    store.update_last_session(
        context_path=first_context_path,
        last_run_id="run-existing",
        last_runtime_state="halted",
        last_shutdown_reason="mt5_disconnect",
    )

    second = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT, create_new=True)
    second_context_path = Path(second["binding"]["context_path"])

    assert second["binding"]["context_key"] != first["binding"]["context_key"]
    assert first_resume_prompt.read_text(encoding="utf-8") == "# Resume Prompt\n\n- catatan lama harus tetap ada.\n"
    assert store.load_last_session(context_path=first_context_path)["last_run_id"] == "run-existing"
    assert store.load_last_session(context_path=first_context_path)["last_shutdown_reason"] == "mt5_disconnect"
    assert (second_context_path / "resume" / "resume_prompt.md").exists()
    assert store.load_runtime_state()["context_key"] == second["binding"]["context_key"]
    assert "<!-- bot-ea managed resume prompt -->" in (second_context_path / "resume" / "resume_prompt.md").read_text(encoding="utf-8")


def test_rebinding_existing_context_does_not_overwrite_resume_prompt(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()

    initial = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)
    context_path = Path(initial["binding"]["context_path"])
    resume_prompt = context_path / "resume" / "resume_prompt.md"
    custom_prompt = "# Resume Prompt\n\n- lanjutkan konteks lama.\n- jangan reset manual notes.\n"
    resume_prompt.write_text(custom_prompt, encoding="utf-8")

    rebound = store.build_resume_state(
        settings=settings,
        fingerprint_payload=FINGERPRINT,
        context_key=initial["binding"]["context_key"],
    )

    assert rebound["binding"]["context_key"] == initial["binding"]["context_key"]
    assert rebound["binding"]["created_now"] is False
    assert resume_prompt.read_text(encoding="utf-8") == custom_prompt
    assert store.load_runtime_state()["context_path"] == rebound["binding"]["context_path"]


def test_build_resume_state_replaces_stale_runtime_state_with_existing_context(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()
    context_root = Path(settings.ai_context_root)
    existing_path = context_root / "broker_demo_demo_server_123456"
    existing_path.mkdir(parents=True, exist_ok=True)
    store.save_last_session(
        context_path=existing_path,
        payload={
            "account_fingerprint": dict(FINGERPRINT),
            "last_run_id": "run-persisted",
            "last_runtime_state": "stopped",
        },
    )
    store.save_runtime_state(
        {
            "active_account_fingerprint": dict(FINGERPRINT),
            "context_key": "stale_context_key",
            "context_path": str((context_root / "stale_context_key").resolve()),
            "last_runtime_state": "running",
            "last_run_id": "run-stale",
            "last_shutdown_reason": "unknown",
        }
    )

    result = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)
    runtime_state = store.load_runtime_state()

    assert result["binding"]["context_key"] == "broker_demo_demo_server_123456"
    assert result["binding"]["mapping_source"] == "existing"
    assert runtime_state["context_key"] == "broker_demo_demo_server_123456"
    assert runtime_state["context_path"] == str(existing_path.resolve())
    assert runtime_state["last_runtime_state"] == "ready"


def test_managed_resume_prompt_includes_account_notes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    settings = store.default_settings()
    result = store.build_resume_state(settings=settings, fingerprint_payload=FINGERPRINT)
    context_path = Path(result["binding"]["context_path"])

    (context_path / "documents" / "broker_notes.md").write_text("# Broker Notes\n\n- spread lebar saat sesi Asia\n", encoding="utf-8")
    (context_path / "documents" / "operator_notes.md").write_text("# Operator Notes\n\n- hindari entry saat news merah\n", encoding="utf-8")
    store.update_last_session(
        context_path=context_path,
        last_run_id="run-456",
        last_runtime_state="stopped",
        last_shutdown_reason="operator_stop",
    )

    resume_prompt = (context_path / "resume" / "resume_prompt.md").read_text(encoding="utf-8")
    assert "## Broker Notes" in resume_prompt
    assert "spread lebar saat sesi Asia" in resume_prompt
    assert "## Operator Notes" in resume_prompt
    assert "hindari entry saat news merah" in resume_prompt
