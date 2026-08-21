from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/verify_g15_full_parity.py"
SPEC = importlib.util.spec_from_file_location("verify_g15_full_parity", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_full_parity_report_covers_every_profile_pipeline_and_exact_field() -> None:
    report = MODULE.build_report(ROOT)

    assert report["status"] == "PASS"
    assert set(report["profiles"]) == {"GOLDI", "GOLDM"}
    assert report["pipelines"] == list(MODULE.PIPELINES)
    assert report["exact_fields"] == list(MODULE.EXACT_FIELDS)
    assert report["parity"]["cross_profile_event_count"] == 0
    assert report["parity"]["equity_curve_role"] == "SUPPLEMENTARY_ONLY"
    assert report["production_real_orders"] == "DISABLED"
    for profile in report["profiles"].values():
        assert profile["observed_price_delta_ticks"] <= profile["maximum_price_delta_ticks"]


@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("status",), "FAIL"),
        (("profiles", "GOLDM", "fingerprint"), "0" * 64),
        (("parity", "cross_profile_event_count"), 1),
        (("production_real_orders",), "ENABLED"),
    ],
)
def test_certification_rejects_mutated_claims(path: tuple[str, ...], replacement) -> None:
    report = MODULE.build_report(ROOT)
    mutated = copy.deepcopy(report)
    target = mutated
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = replacement

    with pytest.raises(MODULE.CertificationError, match="differs"):
        MODULE.validate_report(ROOT, mutated)


def test_all_input_hashes_are_recomputed_from_repository_bytes() -> None:
    report = MODULE.build_report(ROOT)

    assert set(report["input_sha256"]) == set(MODULE.INPUT_PATHS)
    for relative, digest in report["input_sha256"].items():
        assert MODULE._sha256(ROOT / relative) == digest
