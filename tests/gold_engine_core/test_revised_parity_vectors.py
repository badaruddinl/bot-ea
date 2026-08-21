from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from gold_engine_core import load_named_profile

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VECTOR_PATH = REPOSITORY_ROOT / "corpus" / "revised_parity" / "vectors.json"
SETUP_VECTOR_PATH = REPOSITORY_ROOT / "corpus" / "revised_parity" / "setup_vectors.json"


def test_revised_parity_vectors_are_complete_profile_symmetric_and_hashed() -> None:
    raw = VECTOR_PATH.read_bytes()
    payload = json.loads(raw)
    checksum = VECTOR_PATH.with_suffix(".sha256").read_text(encoding="ascii").split()

    assert checksum == [hashlib.sha256(raw).hexdigest(), VECTOR_PATH.name]
    assert len(payload) == 10
    assert {(item["profile_id"], item["case_id"]) for item in payload} == {
        (profile_id, case_id)
        for profile_id in ("GOLDI", "GOLDM")
        for case_id in (
            "range_entry",
            "sell_range_entry",
            "no_setup",
            "sub_one_r_obstacle",
            "momentum_entry",
        )
    }
    by_case: dict[str, list[dict[str, object]]] = {}
    for item in payload:
        assert (
            item["profile_fingerprint"]
            == load_named_profile(REPOSITORY_ROOT, item["profile_id"]).fingerprint
        )
        by_case.setdefault(item["case_id"], []).append(item["expected"])
    assert all(values[0] == values[1] for values in by_case.values())


def test_revised_parity_vector_generator_is_byte_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "vectors.json"
    setup_output = tmp_path / "setup-vectors.json"
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "build_g12_revised_vectors.py"),
        "--output",
        str(output),
        "--setup-output",
        str(setup_output),
    ]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    first_raw = output.read_bytes()
    first_setup_raw = setup_output.read_bytes()
    second = subprocess.run(command, check=True, capture_output=True, text=True)

    assert output.read_bytes() == first_raw
    assert setup_output.read_bytes() == first_setup_raw
    assert first.stdout == second.stdout


def test_revised_setup_vectors_cover_exact_state_reason_and_restart_contract() -> None:
    raw = SETUP_VECTOR_PATH.read_bytes()
    payload = json.loads(raw)
    checksum = SETUP_VECTOR_PATH.with_suffix(".sha256").read_text(encoding="ascii").split()
    cases = (
        "setup_accept",
        "reinforcement",
        "restart_restore",
        "consume_restart_no_resurrection",
        "expiry_restart",
        "opposite_cancel_restart",
    )

    assert checksum == [hashlib.sha256(raw).hexdigest(), SETUP_VECTOR_PATH.name]
    assert len(payload) == 12
    assert {(item["profile_id"], item["case_id"]) for item in payload} == {
        (profile_id, case_id) for profile_id in ("GOLDI", "GOLDM") for case_id in cases
    }
    by_case: dict[str, list[tuple[object, object]]] = {}
    for item in payload:
        assert (
            item["profile_fingerprint"]
            == load_named_profile(REPOSITORY_ROOT, item["profile_id"]).fingerprint
        )
        by_case.setdefault(item["case_id"], []).append((item["expected"], item["state"]))
    assert all(values[0] == values[1] for values in by_case.values())
    expiry = next(item for item in payload if item["case_id"] == "expiry_restart")
    opposite = next(item for item in payload if item["case_id"] == "opposite_cancel_restart")
    consumed = next(
        item for item in payload if item["case_id"] == "consume_restart_no_resurrection"
    )
    assert expiry["expected"]["reason"] == "WATCH_WINDOW_EXPIRED"
    assert opposite["expected"]["reason"] == "OPPOSITE_M5_SETUP_ACCEPTED"
    assert consumed["expected"] is None
