from __future__ import annotations

import inspect
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_module():
    import importlib.util

    script = ROOT / "scripts/run_g17_telegram_e2e.py"
    spec = importlib.util.spec_from_file_location("run_g17_telegram_e2e", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_chat_ids_are_normalized_without_exposing_raw_values() -> None:
    module = load_module()

    assert module.normalize_chat_ids("-123, 456;bad,-123,0") == ("-123", "456")


def test_actual_runner_is_sender_only_and_hashes_recipient_ids() -> None:
    module = load_module()
    source = inspect.getsource(module)

    assert "send_message" in source
    assert "chat_id_sha256" in source
    assert "TELEGRAM_BOT_TOKEN" in source
    assert "G17_APPROVED_CHAT_IDS" in source
    assert "getUpdates" not in source
    assert "get_updates" not in source
