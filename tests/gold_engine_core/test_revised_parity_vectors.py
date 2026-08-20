from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VECTOR_PATH = REPOSITORY_ROOT / "corpus" / "revised_parity" / "vectors.json"


def test_revised_parity_vectors_are_complete_profile_symmetric_and_hashed() -> None:
    raw = VECTOR_PATH.read_bytes()
    payload = json.loads(raw)
    checksum = VECTOR_PATH.with_suffix(".sha256").read_text(encoding="ascii").split()

    assert checksum == [hashlib.sha256(raw).hexdigest(), VECTOR_PATH.name]
    assert len(payload) == 8
    assert {(item["profile_id"], item["case_id"]) for item in payload} == {
        (profile_id, case_id)
        for profile_id in ("GOLDI", "GOLDM")
        for case_id in (
            "range_entry",
            "no_setup",
            "sub_one_r_obstacle",
            "momentum_entry",
        )
    }
    by_case: dict[str, list[dict[str, object]]] = {}
    for item in payload:
        by_case.setdefault(item["case_id"], []).append(item["expected"])
    assert all(values[0] == values[1] for values in by_case.values())


def test_revised_parity_vector_generator_is_byte_deterministic(tmp_path: Path) -> None:
    output = tmp_path / "vectors.json"
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "build_g12_revised_vectors.py"),
        "--output",
        str(output),
    ]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    first_raw = output.read_bytes()
    second = subprocess.run(command, check=True, capture_output=True, text=True)

    assert output.read_bytes() == first_raw
    assert first.stdout == second.stdout
