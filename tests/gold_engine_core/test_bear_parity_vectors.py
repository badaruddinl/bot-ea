from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from gold_engine_core import load_named_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VECTOR_PATH = REPOSITORY_ROOT / "corpus" / "bear_parity" / "vectors.json"


def test_bear_vectors_are_hashed_profile_symmetric_and_transition_complete() -> None:
    raw = VECTOR_PATH.read_bytes()
    payload = json.loads(raw)
    checksum = VECTOR_PATH.with_suffix(".sha256").read_text(encoding="ascii").split()
    cases = {
        "happy_path_entry",
        "watch_m1_restart_state",
        "h1_rejected",
        "m5_acceptance_cancelled",
        "m1_expired",
    }

    assert checksum == [hashlib.sha256(raw).hexdigest(), VECTOR_PATH.name]
    assert len(payload) == 10
    assert {(item["profile_id"], item["case_id"]) for item in payload} == {
        (profile_id, case_id) for profile_id in ("GOLDI", "GOLDM") for case_id in cases
    }
    for item in payload:
        assert (
            item["profile_fingerprint"]
            == load_named_profile(REPOSITORY_ROOT, item["profile_id"]).fingerprint
        )
    by_case: dict[str, list[dict[str, object]]] = {}
    for item in payload:
        by_case.setdefault(item["case_id"], []).append(item["expected"])
    for case_id, values in by_case.items():
        if case_id == "happy_path_entry":
            assert values[0]["signal"]["profile_id"] == "GOLDI"
            assert values[1]["signal"]["profile_id"] == "GOLDM"
            left = dict(values[0]["signal"])
            right = dict(values[1]["signal"])
            for key in (
                "profile_id",
                "setup_id",
                "signal_id",
                "symbol",
                "stop",
                "target",
                "structural_stop",
            ):
                left.pop(key)
                right.pop(key)
            assert left == right
            assert values[1]["signal"]["stop"] > values[0]["signal"]["stop"]
            assert values[1]["signal"]["target"] < values[0]["signal"]["target"]
        else:
            assert values[0]["phase"] == values[1]["phase"]
            assert [event["reason"] for event in values[0]["events"]] == [
                event["reason"] for event in values[1]["events"]
            ]


def test_bear_vector_generator_is_byte_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "vectors.json"
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "build_g13_bear_vectors.py"),
        "--output",
        str(output),
    ]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    first_raw = output.read_bytes()
    second = subprocess.run(command, check=True, capture_output=True, text=True)

    assert output.read_bytes() == first_raw
    assert first.stdout == second.stdout
