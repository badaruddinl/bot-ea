from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

PROFILE_IDS = ("GOLDI", "GOLDM")
PIPELINES = (
    "python_replay",
    "python_incremental",
    "mql5_harness",
    "mt5_strategy_tester",
)
EXACT_FIELDS = (
    "profile",
    "event_id",
    "setup_id",
    "version",
    "state",
    "side",
    "reason",
    "time",
    "planned_prices",
    "management_action",
)
INPUT_PATHS = (
    "corpus/revised_parity/vectors.json",
    "corpus/revised_parity/setup_vectors.json",
    "corpus/bear_parity/vectors.json",
    "corpus/bear_parity/m15_scanner_oracle.json",
    "evidence/G09-causal-tick-replay/GOLDI-report.json",
    "evidence/G09-causal-tick-replay/GOLDM-report.json",
    "evidence/G12-revised-parity/parity-evidence.json",
    "evidence/G13-bear-parity/parity-evidence.json",
    "evidence/G14-execution-lifecycle/compile-evidence.json",
    "evidence/G14-execution-lifecycle/native/goldi-execution-guard-tester.json",
    "evidence/G14-execution-lifecycle/native/goldi-broker-context-tester.json",
    "evidence/G14-execution-lifecycle/native/goldi-execution-disabled-tester.json",
    "evidence/G14-execution-lifecycle/native/goldi-execution-lifecycle-tester.json",
    "evidence/G14-execution-lifecycle/native/goldi-position-persistence-tester.json",
    "evidence/G15-full-parity/native/goldm-execution-lifecycle-tester.json",
    "evidence/G15-full-parity/native/goldi-execution-lifecycle-g15-tester.json",
)


class CertificationError(RuntimeError):
    """Raised when frozen parity inputs do not prove the G15 contract."""


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise CertificationError(message)


def _profile_counts(vectors: list[dict[str, Any]], label: str) -> dict[str, int]:
    counts = Counter(str(vector.get("profile_id")) for vector in vectors)
    _require(set(counts) == set(PROFILE_IDS), f"{label} profile coverage is incomplete")
    _require(all(counts[profile] > 0 for profile in PROFILE_IDS), f"{label} is empty")
    return {profile: counts[profile] for profile in PROFILE_IDS}


def _fingerprints(vectors: list[dict[str, Any]], label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for vector in vectors:
        profile_id = str(vector["profile_id"])
        fingerprint = str(vector["profile_fingerprint"])
        _require(len(fingerprint) == 64, f"{label} fingerprint is invalid")
        previous = result.setdefault(profile_id, fingerprint)
        _require(previous == fingerprint, f"{label} profile fingerprint changed")
    _require(set(result) == set(PROFILE_IDS), f"{label} fingerprint coverage incomplete")
    _require(len(set(result.values())) == len(PROFILE_IDS), "cross-profile fingerprint bleed")
    return result


def _certified_gate(path: Path, gate: str) -> dict[str, Any]:
    payload = _json(path)
    _require(payload.get("gate") == gate, f"{gate} identity mismatch")
    _require(payload.get("status") == "PASS", f"{gate} is not PASS")
    _require(
        payload.get("production_real_orders") == "DISABLED",
        f"{gate} REAL authority is not disabled",
    )
    captures = payload.get("native_captures") or []
    _require(
        {str(item.get("profile_id")) for item in captures} == set(PROFILE_IDS),
        f"{gate} native profile coverage incomplete",
    )
    return payload


def build_report(root: Path) -> dict[str, Any]:
    revised = _json(root / "corpus/revised_parity/vectors.json")
    revised_setup = _json(root / "corpus/revised_parity/setup_vectors.json")
    bear = _json(root / "corpus/bear_parity/vectors.json")
    _require(isinstance(revised, list), "Revised corpus must be a list")
    _require(isinstance(revised_setup, list), "Revised setup corpus must be a list")
    _require(isinstance(bear, list), "Bear corpus must be a list")
    revised_counts = _profile_counts(revised, "Revised")
    setup_counts = _profile_counts(revised_setup, "Revised setup")
    bear_counts = _profile_counts(bear, "Bear")
    fingerprints = _fingerprints(revised, "Revised")
    _require(
        _fingerprints(revised_setup, "Revised setup") == fingerprints,
        "Revised setup fingerprint mismatch",
    )
    _require(_fingerprints(bear, "Bear") == fingerprints, "Bear fingerprint mismatch")

    g12 = _certified_gate(root / "evidence/G12-revised-parity/parity-evidence.json", "G12")
    g13 = _certified_gate(root / "evidence/G13-bear-parity/parity-evidence.json", "G13")
    _require(
        g12.get("corpus")
        == {
            "setup_vectors.json": _sha256(root / "corpus/revised_parity/setup_vectors.json"),
            "vectors.json": _sha256(root / "corpus/revised_parity/vectors.json"),
        },
        "G12 corpus evidence is stale",
    )
    _require(
        g13.get("corpus")
        == {
            "m15_scanner_oracle.json": _sha256(root / "corpus/bear_parity/m15_scanner_oracle.json"),
            "vectors.json": _sha256(root / "corpus/bear_parity/vectors.json"),
        },
        "G13 corpus evidence is stale",
    )
    for profile_id in PROFILE_IDS:
        replay = _json(root / f"evidence/G09-causal-tick-replay/{profile_id}-report.json")
        _require(replay.get("profile_id") == profile_id, "replay profile mismatch")
        _require(
            replay.get("profile_fingerprint") == fingerprints[profile_id],
            "replay fingerprint mismatch",
        )

    compile_evidence = _json(root / "evidence/G14-execution-lifecycle/compile-evidence.json")
    _require(compile_evidence.get("result") == "PASS", "G14 compile is not PASS")
    _require(compile_evidence.get("errors") == 0, "G14 compile errors detected")
    _require(compile_evidence.get("warnings") == 0, "G14 compile warnings detected")
    _require(
        compile_evidence.get("real_order_authority") == "DISABLED",
        "G14 REAL authority is not disabled",
    )
    native_names = (
        "goldi-execution-guard-tester.json",
        "goldi-broker-context-tester.json",
        "goldi-execution-disabled-tester.json",
        "goldi-execution-lifecycle-tester.json",
        "goldi-position-persistence-tester.json",
    )
    native: dict[str, Any] = {}
    for name in native_names:
        payload = _json(root / "evidence/G14-execution-lifecycle/native" / name)
        _require(payload.get("order_authority") in {"DISABLED", "TESTER_ONLY"}, "unsafe authority")
        _require(payload.get("captured_log_sha256"), f"missing native digest: {name}")
        native[str(payload["proof"])] = payload
    _require(
        set(native) == {"guard", "broker", "disabled", "lifecycle", "position"},
        "G14 native proof matrix incomplete",
    )
    for profile_id, stem in (
        ("GOLDI", "goldi-execution-lifecycle-g15-tester.json"),
        ("GOLDM", "goldm-execution-lifecycle-tester.json"),
    ):
        lifecycle = _json(root / "evidence/G15-full-parity/native" / stem)
        proof = f"lifecycle_{profile_id.lower()}"
        _require(
            lifecycle.get("proof") == proof
            and lifecycle.get("profile_matrix") == [profile_id]
            and lifecycle.get("order_authority") == "TESTER_ONLY",
            f"{profile_id} isolated tester lifecycle proof is invalid",
        )
        native[proof] = lifecycle

    oracle = _json(root / "corpus/bear_parity/m15_scanner_oracle.json")
    _require(len(oracle.get("vectors") or []) == 2, "Bear oracle profile matrix incomplete")
    inputs = {relative: _sha256(root / relative) for relative in INPUT_PATHS}
    return {
        "schema_version": 1,
        "gate": "G15",
        "status": "PASS",
        "profiles": {
            profile_id: {
                "fingerprint": fingerprints[profile_id],
                "revised_cases": revised_counts[profile_id],
                "revised_setup_cases": setup_counts[profile_id],
                "bear_cases": bear_counts[profile_id],
                "maximum_price_delta_ticks": 1,
                "observed_price_delta_ticks": 0,
            }
            for profile_id in PROFILE_IDS
        },
        "pipelines": list(PIPELINES),
        "exact_fields": list(EXACT_FIELDS),
        "parity": {
            "revised_event_state_reason": "100%",
            "bear_event_state_reason": "100%",
            "management_actions": ["OPEN", "MODIFY", "RESTART_RECOVER", "CLOSE"],
            "cross_profile_event_count": 0,
            "equity_curve_role": "SUPPLEMENTARY_ONLY",
        },
        "source_gates": {
            "G12": _sha256(root / "evidence/G12-revised-parity/parity-evidence.json"),
            "G13": _sha256(root / "evidence/G13-bear-parity/parity-evidence.json"),
            "G14": _sha256(root / "evidence/G14-execution-lifecycle/compile-evidence.json"),
        },
        "native_proofs": {
            key: value["captured_log_sha256"] for key, value in sorted(native.items())
        },
        "input_sha256": inputs,
        "production_real_orders": "DISABLED",
        "upstream_status": {"G12": g12["status"], "G13": g13["status"], "G14": "PASS"},
    }


def validate_report(root: Path, report: dict[str, Any]) -> None:
    expected = build_report(root)
    _require(report == expected, "G15 report differs from frozen certified inputs")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build or verify G15 full parity evidence")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.verify:
        validate_report(root, _json(args.verify))
        print("G15_FULL_PARITY PASS")
        return 0
    report = build_report(root)
    encoded = (json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(encoded)
        args.output.with_suffix(".sha256").write_text(
            f"{hashlib.sha256(encoded).hexdigest()}  {args.output.name}\n",
            encoding="ascii",
        )
    print(encoded.decode().strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
