from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]


def _load_script() -> ModuleType:
    path = ROOT / "scripts/verify_g21_release.py"
    spec = importlib.util.spec_from_file_location("verify_g21_release", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_release_tree_passes_strict_verifier() -> None:
    module = _load_script()

    result = module.verify(ROOT, ROOT / "release")

    assert result["status"] == "PASS"
    assert result["violations"] == []
    assert result["production_real_orders"] == "DISABLED"


def test_binary_mutation_fails_fresh_vm_and_checksum(tmp_path: Path) -> None:
    module = _load_script()
    release = tmp_path / "release"
    shutil.copytree(ROOT / "release", release)
    binary = release / "GoldEngine-GOLDM-v1.1.0.ex5"
    binary.write_bytes(binary.read_bytes() + b"mutation")

    result = module.verify(ROOT, release)

    assert result["status"] == "FAIL"
    assert any("GOLDM binary does not match fresh VM" in item for item in result["violations"])
    assert any("SHA256SUMS mismatch" in item for item in result["violations"])
