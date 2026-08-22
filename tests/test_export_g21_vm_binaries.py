from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType


def _load_script() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts" / "export_g21_vm_binaries.py"
    spec = importlib.util.spec_from_file_location("export_g21_vm_binaries", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_export_copies_only_exact_certified_profile_binaries(tmp_path: Path) -> None:
    module = _load_script()
    bindings = []
    for profile_id, payload in (("GOLDI", b"goldi"), ("GOLDM", b"goldm")):
        source = tmp_path / profile_id / f"{profile_id}.ex5"
        source.parent.mkdir()
        source.write_bytes(payload)
        bindings.append(
            {
                "profile_id": profile_id,
                "ea_binary_path": str(source),
                "ea_sha256": _sha256(payload),
            }
        )
    config = tmp_path / "g20.json"
    config.write_text(
        json.dumps({"production_real_orders": "DISABLED", "terminals": bindings}),
        encoding="utf-8",
    )

    receipt = module.export(config, tmp_path / "release")

    assert receipt["status"] == "PASS"
    assert receipt["production_real_orders"] == "DISABLED"
    assert (tmp_path / "release" / "GoldEngine-GOLDi-v1.1.0.ex5").read_bytes() == b"goldi"
    assert (tmp_path / "release" / "GoldEngine-GOLDm-v1.1.0.ex5").read_bytes() == b"goldm"
    assert (tmp_path / "release" / "vm-binary-export.sha256").is_file()


def test_export_rejects_hash_mismatch_and_enabled_real(tmp_path: Path) -> None:
    module = _load_script()
    source = tmp_path / "binary.ex5"
    source.write_bytes(b"binary")
    bindings = [
        {"profile_id": profile_id, "ea_binary_path": str(source), "ea_sha256": "0" * 64}
        for profile_id in ("GOLDI", "GOLDM")
    ]
    config = tmp_path / "g20.json"
    config.write_text(
        json.dumps({"production_real_orders": "DISABLED", "terminals": bindings}),
        encoding="utf-8",
    )
    try:
        module.export(config, tmp_path / "release")
    except ValueError as exc:
        assert "hash mismatch" in str(exc)
    else:
        raise AssertionError("mismatched binary hash was accepted")

    config.write_text(
        json.dumps({"production_real_orders": "ENABLED", "terminals": bindings}),
        encoding="utf-8",
    )
    try:
        module.export(config, tmp_path / "release")
    except ValueError as exc:
        assert "REAL orders disabled" in str(exc)
    else:
        raise AssertionError("enabled REAL authority was accepted")
