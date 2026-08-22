from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import cast

_RELEASE_NAMES = {
    "GOLDI": "GoldEngine-GOLDi-v1.1.0.ex5",
    "GOLDM": "GoldEngine-GOLDm-v1.1.0.ex5",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
    ).encode("utf-8")


def export(config_path: Path, output_root: Path) -> dict[str, object]:
    value: object = json.loads(config_path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("G20 config must be an object")
    if value.get("production_real_orders") != "DISABLED":
        raise ValueError("G20 config does not prove REAL orders disabled")
    terminals = value.get("terminals")
    if not isinstance(terminals, list):
        raise ValueError("G20 config terminals must be an array")
    by_profile: dict[str, dict[str, object]] = {}
    for item in terminals:
        if isinstance(item, dict) and item.get("profile_id") in _RELEASE_NAMES:
            by_profile[cast(str, item["profile_id"])] = cast(dict[str, object], item)
    if set(by_profile) != set(_RELEASE_NAMES):
        raise ValueError("G20 config must contain exactly GOLDI and GOLDM")

    output_root.mkdir(parents=True, exist_ok=True)
    artifacts: dict[str, dict[str, object]] = {}
    for profile_id, release_name in _RELEASE_NAMES.items():
        binding = by_profile[profile_id]
        source = Path(str(binding.get("ea_binary_path", "")))
        expected = str(binding.get("ea_sha256", "")).lower()
        if not source.is_file() or len(expected) != 64:
            raise ValueError(f"{profile_id} certified binary binding is invalid")
        actual = _sha256(source)
        if actual != expected:
            raise ValueError(f"{profile_id} certified binary hash mismatch")
        destination = output_root / release_name
        shutil.copyfile(source, destination)
        copied = _sha256(destination)
        if copied != expected:
            raise RuntimeError(f"{profile_id} release copy hash mismatch")
        artifacts[profile_id] = {
            "filename": release_name,
            "sha256": copied,
            "size_bytes": destination.stat().st_size,
        }

    receipt = {
        "schema_version": 1,
        "gate": "G21",
        "status": "PASS",
        "production_real_orders": "DISABLED",
        "artifacts": artifacts,
    }
    raw = _canonical_bytes(receipt)
    receipt_path = output_root / "vm-binary-export.json"
    receipt_path.write_bytes(raw)
    (output_root / "vm-binary-export.sha256").write_text(
        f"{hashlib.sha256(raw).hexdigest()}  {receipt_path.name}\n",
        encoding="ascii",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Export G21 binaries from certified G20 VM bindings")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(export(args.config, args.output_root), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
