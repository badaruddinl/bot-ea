from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

from capture_g12_tester_evidence import validate_block  # noqa: E402

from gold_engine_core import load_named_profile  # noqa: E402


class G12EvidenceError(RuntimeError):
    """Raised when evidence is too weak to certify G12."""


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def verify_sidecar(path: Path) -> str:
    if not path.is_file():
        raise G12EvidenceError(f"artifact is missing: {path}")
    sidecar = path.with_suffix(".sha256")
    if not sidecar.is_file():
        raise G12EvidenceError(f"checksum sidecar is missing: {sidecar}")
    parts = sidecar.read_text(encoding="ascii").split()
    expected = sha256_bytes(path.read_bytes())
    if parts != [expected, path.name]:
        raise G12EvidenceError(f"checksum mismatch: {path}")
    return expected


def verify_corpus() -> dict[str, str]:
    result: dict[str, str] = {}
    expected_cases = {
        "vectors.json": 10,
        "setup_vectors.json": 12,
    }
    for name, count in expected_cases.items():
        path = REPOSITORY_ROOT / "corpus" / "revised_parity" / name
        result[name] = verify_sidecar(path)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list) or len(payload) != count:
            raise G12EvidenceError(f"unexpected G12 corpus size: {name}")
        profiles = {item.get("profile_id") for item in payload if isinstance(item, dict)}
        if profiles != {"GOLDI", "GOLDM"}:
            raise G12EvidenceError(f"G12 corpus is not profile symmetric: {name}")
        for item in payload:
            profile_id = item["profile_id"]
            expected_fingerprint = load_named_profile(REPOSITORY_ROOT, profile_id).fingerprint
            if item.get("profile_fingerprint") != expected_fingerprint:
                raise G12EvidenceError(f"stale profile fingerprint in {name}")
    return result


def verify_compile(evidence_root: Path) -> str:
    path = evidence_root / "compile-evidence.json"
    digest = verify_sidecar(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("gate") != "G12" or payload.get("status") != "COMPILE_PASS":
        raise G12EvidenceError("G12 compile evidence is not PASS")
    if payload.get("production_real_orders") != "DISABLED":
        raise G12EvidenceError("compile evidence does not keep REAL orders disabled")
    profiles = payload.get("profiles")
    if not isinstance(profiles, list) or {item.get("profile_id") for item in profiles} != {
        "GOLDI",
        "GOLDM",
    }:
        raise G12EvidenceError("compile evidence is not dual-profile")
    harness = payload.get("harness")
    if not isinstance(harness, dict) or harness.get("compile_result") != (
        "Result: 0 errors, 0 warnings"
    ):
        raise G12EvidenceError("harness compile evidence is incomplete")
    return digest


def verify_native_capture(
    evidence_root: Path,
    *,
    profile_id: str,
    symbol: str,
    timeframe: str,
    server: str,
) -> dict[str, object]:
    stem = profile_id.lower()
    native = evidence_root / "native"
    log_path = native / f"{stem}-strategy-tester.log"
    log_digest = verify_sidecar(log_path)
    metadata_path = native / f"{stem}-strategy-tester.json"
    if not metadata_path.is_file():
        raise G12EvidenceError(f"native metadata is missing: {metadata_path}")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    expected = {
        "profile_id": profile_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "real_order_authority": "DISABLED",
        "server": server,
        "captured_log": log_path.name,
        "captured_log_sha256": log_digest,
    }
    mismatches = {
        key: (metadata.get(key), value)
        for key, value in expected.items()
        if metadata.get(key) != value
    }
    if mismatches:
        raise G12EvidenceError(f"native metadata mismatch for {profile_id}: {mismatches}")
    validate_block(
        log_path.read_text(encoding="utf-8"),
        symbol=symbol,
        timeframe=timeframe,
        server=server,
    )
    return {
        "captured_log_sha256": log_digest,
        "profile_id": profile_id,
        "symbol": symbol,
        "timeframe": timeframe,
        "server": server,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Certify complete dual-profile G12 evidence")
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
        "gate": "G12",
        "native_captures": captures,
        "production_real_orders": "DISABLED",
        "status": "PASS",
    }
    raw = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    digest = sha256_bytes(raw)
    args.output.with_suffix(".sha256").write_text(
        f"{digest}  {args.output.name}\n",
        encoding="ascii",
    )
    print(f"status=PASS profiles=2 sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
