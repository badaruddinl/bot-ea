from __future__ import annotations

import inspect
import json
from pathlib import Path

from gold_event_bridge import cli


def test_subscriber_state_is_normalized_and_invalid_values_are_ignored(tmp_path: Path) -> None:
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"goldi_subscribers": ["-123", 456, "bad", 0, "-123"]}),
        encoding="utf-8",
    )

    assert cli.load_goldi_subscribers(state) == ("-123", "456")


def test_bridge_runtime_is_sender_only_and_never_polls_telegram() -> None:
    source = inspect.getsource(cli)

    assert "send_message" in source
    assert "get_updates" not in source
    assert "getUpdates" not in source


def test_cli_requires_two_profile_spools_and_one_database() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(
        [
            "--goldi-spool",
            "GOLDI.jsonl",
            "--goldm-spool",
            "GOLDM.jsonl",
            "--database",
            "events.db",
            "--once",
        ]
    )

    assert args.goldi_spool.name == "GOLDI.jsonl"
    assert args.goldm_spool.name == "GOLDM.jsonl"
    assert args.database.name == "events.db"
    assert args.once
