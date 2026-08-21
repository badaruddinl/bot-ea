from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from capture_g13_tester_evidence import validate_block  # noqa: E402


class G13EvidenceError(RuntimeError):
    """Raised when evidence is too weak to certify G13."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify_sidecar(path: Path) -> str:
    if not path.is_file() or not path.with_suffix(".sha256").is_file():
        raise G13EvidenceError(f"artifact or checksum is missing: {path}")
    digest = sha256_bytes(path.read_bytes())
    if path.with_suffix(".sha256").read_text(encoding="ascii").split() != [digest, path.name]:
        raise G13EvidenceError(f"checksum mismatch: {path}")
    return digest


def verify_corpus() -> dict[str, str]:
    root = REPOSITORY_ROOT / "corpus" / "bear_parity"
    vectors = root / "vectors.json"
    oracle = root / "m15_scanner_oracle.json"
    result = {path.name: verify_sidecar(path) for path in (vectors, oracle)}
    vector_payload = json.loads(vectors.read_text(encoding="utf-8"))
    if not isinstance(vector_payload, list) or len(vector_payload) != 10:
        raise G13EvidenceError("G13 vector corpus must contain exactly 10 cases")
    if {item.get("profile_id") for item in vector_payload} != {"GOLDI", "GOLDM"}:
        raise G13EvidenceError("G13 vector corpus is not profile symmetric")
    oracle_payload = json.loads(oracle.read_text(encoding="utf-8"))
    if set(oracle_payload.get("profiles", {})) != {"GOLDI", "GOLDM"}:
        raise G13EvidenceError("G13 M15 oracle is not dual-profile")
    return result


def verify_compile(evidence_root: Path) -> str:
    path = evidence_root / "compile-evidence.json"
    digest = verify_sidecar(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("gate") != "G13" or payload.get("status") != "COMPILE_PASS":
        raise G13EvidenceError("G13 compile evidence is not PASS")
    if payload.get("production_real_orders") != "DISABLED":
        raise G13EvidenceError("REAL order authority is not disabled")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or {item.get("profile_id") for item in profiles} != {
        "GOLDI",
        "GOLDM",
    }:
        raise G13EvidenceError("compile evidence is not dual-profile")
    harness = payload.get("harness")
    if not isinstance(harness, dict) or harness.get("compile_result") != (
        "Result: 0 errors, 0 warnings"
    ):
        raise G13EvidenceError("harness compile evidence is incomplete")
    return digest


def verify_native_capture(
    evidence_root: Path, *, profile_id: str, symbol: str, timeframe: str, server: str
) -> dict[str, str]:
    stem = profile_id.lower()
    native = evidence_root / "native"
    log_path = native / f"{stem}-bear-strategy-tester.log"
    digest = verify_sidecar(log_path)
    metadata_path = native / f"{stem}-bear-strategy-tester.json"
    if not metadata_path.is_file():
        raise G13EvidenceError(f"native metadata is missing: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {
        "profile_id": profile_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "real_order_authority": "DISABLED",
        "server": server,
        "captured_log": log_path.name,
        "captured_log_sha256": digest,
    }
    mismatches = {
        key: (metadata.get(key), value)
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if mismatches:
        raise G13EvidenceError(f"native metadata mismatch for {profile_id}: {mismatches}")
    validate_block(
        log_path.read_text(encoding="utf-8"), symbol=symbol, timeframe=timeframe, server=server
    )
    return {"profile_id": profile_id, "symbol": symbol, "server": server, "sha256": digest}


def main() -> int:
    parser = argparse.ArgumentParser(description="Certify complete dual-profile G13 evidence")
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    captures = [
        verify_native_capture(
            args.evidence_root,
            profile_id="GOLDI",
            symbol="GOLD.i#",
            timeframe="M15",
            server="XMGlobal-MT5 5",
        ),
        verify_native_capture(
            args.evidence_root,
            profile_id="GOLDM",
            symbol="GOLDm#",
            timeframe="M15",
            server="XMGlobal-MT5 14",
        ),
    ]
    payload = {
        "compile_evidence_sha256": verify_compile(args.evidence_root),
        "corpus": verify_corpus(),
        "gate": "G13",
        "native_captures": captures,
        "production_real_orders": "DISABLED",
        "status": "PASS",
    }
    raw = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    digest = sha256_bytes(raw)
    args.output.with_suffix(".sha256").write_text(
        f"{digest}  {args.output.name}\n", encoding="ascii"
    )
    print(f"status=PASS profiles=2 sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
