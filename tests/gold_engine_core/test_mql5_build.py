from __future__ import annotations

from pathlib import Path

import pytest

from gold_engine_core import Mql5BuildError, verify_g11_compile_artifacts


def write_fixture(root: Path, profile: str, *, result: str) -> None:
    stem = f"GoldEngine-{profile}"
    source_root = root / "mt5" / "Experts" / "bot-ea"
    evidence_root = root / "evidence"
    source_root.mkdir(parents=True, exist_ok=True)
    evidence_root.mkdir(parents=True, exist_ok=True)
    (source_root / f"{stem}.mq5").write_text(f"// {profile}\n", encoding="utf-8")
    (source_root / f"{stem}.ex5").write_bytes((profile.encode("ascii") * 1024)[:2048])
    (evidence_root / f"{stem}.compile.log").write_text(
        f"{result}\n",
        encoding="utf-16",
    )


def test_g11_compile_artifacts_are_profile_distinct_and_warning_clean(
    tmp_path: Path,
) -> None:
    write_fixture(tmp_path, "GOLDi", result="Result: 0 errors, 0 warnings")
    write_fixture(tmp_path, "GOLDm", result="Result: 0 errors, 0 warnings")

    artifacts = verify_g11_compile_artifacts(tmp_path, tmp_path / "evidence")

    assert [artifact.profile_id for artifact in artifacts] == ["GOLDI", "GOLDM"]
    assert artifacts[0].binary_sha256 != artifacts[1].binary_sha256
    assert all(artifact.binary_size >= 1024 for artifact in artifacts)


def test_g11_compile_verifier_rejects_warning_missing_and_duplicate_binary(
    tmp_path: Path,
) -> None:
    write_fixture(tmp_path, "GOLDi", result="Result: 0 errors, 1 warnings")
    write_fixture(tmp_path, "GOLDm", result="Result: 0 errors, 0 warnings")
    with pytest.raises(Mql5BuildError, match="not clean"):
        verify_g11_compile_artifacts(tmp_path, tmp_path / "evidence")

    write_fixture(tmp_path, "GOLDi", result="Result: 0 errors, 0 warnings")
    goldi = tmp_path / "mt5" / "Experts" / "bot-ea" / "GoldEngine-GOLDi.ex5"
    goldm = tmp_path / "mt5" / "Experts" / "bot-ea" / "GoldEngine-GOLDm.ex5"
    goldm.write_bytes(goldi.read_bytes())
    with pytest.raises(Mql5BuildError, match="share one hash"):
        verify_g11_compile_artifacts(tmp_path, tmp_path / "evidence")

    goldm.unlink()
    with pytest.raises(Mql5BuildError, match="binary is missing"):
        verify_g11_compile_artifacts(tmp_path, tmp_path / "evidence")
