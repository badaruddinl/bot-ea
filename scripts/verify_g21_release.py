from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import cast

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core.profile import ProfileManifest, load_named_profile  # noqa: E402

_REQUIRED_FILES = {
    "GoldEngine-GOLDi-v1.1.0.ex5",
    "GoldEngine-GOLDm-v1.1.0.ex5",
    "SHA256SUMS.txt",
    "source-commit.txt",
    "build-environment.md",
    "profile-GOLDI-manifest.json",
    "profile-GOLDM-manifest.json",
    "parity-GOLDI.md",
    "parity-GOLDM.md",
    "e2e-GOLDI.md",
    "e2e-GOLDM.md",
    "cross-profile-isolation.md",
    "failure-recovery.md",
    "resource-storage-latency.md",
    "fresh-vm-GOLDI.md",
    "fresh-vm-GOLDM.md",
    "known-limitations.md",
    "rollback.md",
    "rollback/GoldEngine-GOLDi-pre-G20.ex5",
    "rollback/GoldEngine-GOLDm-pre-G20.ex5",
    "vm-binary-export.json",
    "vm-binary-export.sha256",
}
_CERTIFICATIONS = {
    "G10": "G10-reference-live-validation",
    "G15": "G15-full-parity",
    "G17": "G17-happy-path-e2e",
    "G18": "G18-failure-restart-e2e",
    "G19": "G19-resource-storage-latency",
    "G20": "G20-fresh-vm-acceptance",
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA1 = re.compile(r"^[0-9a-f]{40}$")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, object]:
    value: object = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must be a JSON object")
    return cast(dict[str, object], value)


def _release_files(release_root: Path) -> set[str]:
    return {
        path.relative_to(release_root).as_posix()
        for path in release_root.rglob("*")
        if path.is_file()
    }


def _verify_sums(release_root: Path, violations: list[str]) -> None:
    sums_path = release_root / "SHA256SUMS.txt"
    parsed: dict[str, str] = {}
    if not sums_path.is_file():
        violations.append("SHA256SUMS.txt is missing")
        return
    for line in sums_path.read_text(encoding="ascii").splitlines():
        parts = line.split("  ", 1)
        if len(parts) != 2 or not _SHA256.fullmatch(parts[0]):
            violations.append("SHA256SUMS.txt contains an invalid line")
            continue
        parsed[parts[1]] = parts[0]
    expected_names = _release_files(release_root) - {"SHA256SUMS.txt"}
    if set(parsed) != expected_names:
        violations.append("SHA256SUMS.txt file set mismatch")
    for name, expected in parsed.items():
        path = release_root / Path(name)
        if not path.is_file() or _sha256(path) != expected:
            violations.append(f"SHA256SUMS mismatch: {name}")


def verify(repository_root: Path, release_root: Path) -> dict[str, object]:
    violations: list[str] = []
    present = _release_files(release_root)
    missing = sorted(_REQUIRED_FILES - present)
    if missing:
        violations.append("missing release files: " + ",".join(missing))
    _verify_sums(release_root, violations)

    export = _read_json(release_root / "vm-binary-export.json")
    if export.get("status") != "PASS" or export.get("production_real_orders") != "DISABLED":
        violations.append("VM binary export is not safe PASS")
    g20 = _read_json(repository_root / "evidence/G20-fresh-vm-acceptance/certification.json")
    export_profiles = cast(dict[str, object], export.get("artifacts", {}))
    g20_profiles = cast(dict[str, object], g20.get("profiles", {}))
    binary_hashes: dict[str, str] = {}
    for profile_id, filename in {
        "GOLDI": "GoldEngine-GOLDi-v1.1.0.ex5",
        "GOLDM": "GoldEngine-GOLDm-v1.1.0.ex5",
    }.items():
        actual = _sha256(release_root / filename)
        binary_hashes[profile_id] = actual
        export_entry = cast(dict[str, object], export_profiles.get(profile_id, {}))
        g20_entry = cast(dict[str, object], g20_profiles.get(profile_id, {}))
        if actual != export_entry.get("sha256") or actual != g20_entry.get("binary_sha256"):
            violations.append(f"{profile_id} binary does not match fresh VM")

    profile_fingerprints: dict[str, str] = {}
    for profile_id in ("GOLDI", "GOLDM"):
        release_manifest = _read_json(release_root / f"profile-{profile_id}-manifest.json")
        source_manifest = _read_json(repository_root / f"config/engine_profiles/{profile_id}.json")
        if release_manifest != source_manifest:
            violations.append(f"{profile_id} release manifest differs from source")
        parsed = ProfileManifest.from_payload(release_manifest)
        source = load_named_profile(repository_root, profile_id)
        profile_fingerprints[profile_id] = parsed.fingerprint
        if parsed.fingerprint != source.fingerprint:
            violations.append(f"{profile_id} profile fingerprint mismatch")
        if parsed.order_authority_default != "disabled":
            violations.append(f"{profile_id} default order authority is not disabled")

    source_commit = (release_root / "source-commit.txt").read_text(encoding="ascii").strip()
    if not _GIT_SHA1.fullmatch(source_commit):
        violations.append("source-commit.txt is not an exact Git SHA-1")

    certification_hashes: dict[str, str] = {}
    for gate, directory in _CERTIFICATIONS.items():
        path = repository_root / "evidence" / directory / "certification.json"
        value = _read_json(path)
        certification_hashes[gate] = _sha256(path)
        if value.get("status") != "PASS":
            violations.append(f"{gate} certification is not PASS")
        if value.get("production_real_orders") != "DISABLED":
            violations.append(f"{gate} does not prove REAL orders disabled")

    goal = (repository_root / "BOT-EA-CODEX-GOAL.md").read_text(encoding="utf-8")
    matrix_lines = [line for line in goal.splitlines() if re.match(r"\| G(?:\d|10[A-D])", line)]
    for line in matrix_lines:
        gate = line.split("|", 2)[1].strip()
        if gate.startswith("G21"):
            continue
        if any(status in line for status in ("IN_PROGRESS", "NOT_STARTED", "FAIL", "BLOCKED")):
            violations.append(f"required matrix gate is incomplete: {gate}")

    ledger = (repository_root / "evidence/ledger.md").read_text(encoding="utf-8")
    if re.search(r"\| P1 \|\s*(?:OPEN|IN_PROGRESS|FAIL|BLOCKED)", ledger):
        violations.append("open P1 exists in evidence ledger")
    for name in _REQUIRED_FILES:
        if name.endswith(".md") and name != "known-limitations.md":
            text = (release_root / name).read_text(encoding="utf-8")
            if "DISABLED" not in text and "disabled" not in text:
                violations.append(f"release document lacks disabled authority statement: {name}")

    return {
        "schema_version": 1,
        "gate": "G21",
        "status": "PASS" if not violations else "FAIL",
        "production_real_orders": "DISABLED",
        "source_commit": source_commit,
        "release_sha256sums": _sha256(release_root / "SHA256SUMS.txt"),
        "binary_sha256": binary_hashes,
        "profile_fingerprints": profile_fingerprints,
        "certification_sha256": certification_hashes,
        "p1_open_count": 0 if not any("P1" in value for value in violations) else 1,
        "violations": violations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the complete G21 release tree")
    parser.add_argument("--repository-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--release-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.repository_root.resolve(), args.release_root.resolve())
    raw = (
        json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    args.output.with_suffix(".sha256").write_text(
        f"{hashlib.sha256(raw).hexdigest()}  {args.output.name}\n",
        encoding="ascii",
    )
    print(f"status={result['status']} violations={len(result['violations'])}")
    return 0 if result["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
