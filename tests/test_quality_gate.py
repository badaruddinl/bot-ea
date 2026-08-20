from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "quality_gate.py"
SPEC = importlib.util.spec_from_file_location("quality_gate", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
quality_gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quality_gate)


def test_quality_python_files_selects_only_existing_python_under_quality_roots(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "src" / "new_core").mkdir(parents=True)
    (tmp_path / "src" / "new_core" / "engine.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "helper.py").write_text("VALUE = 2\n", encoding="utf-8")
    monkeypatch.setattr(quality_gate, "REPOSITORY_ROOT", tmp_path)

    selected = quality_gate._quality_python_files(
        (
            Path("src/new_core/engine.py"),
            Path("docs/helper.py"),
            Path("src/new_core/deleted.py"),
            Path("README.md"),
        )
    )

    assert selected == (Path("src/new_core/engine.py"),)


def test_quality_python_files_is_deterministic_and_deduplicated(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / "tests").mkdir()
    for name in ("z_test.py", "a_test.py"):
        (tmp_path / "tests" / name).write_text("pass\n", encoding="utf-8")
    monkeypatch.setattr(quality_gate, "REPOSITORY_ROOT", tmp_path)

    selected = quality_gate._quality_python_files(
        (
            Path("tests/z_test.py"),
            Path("tests/a_test.py"),
            Path("tests/z_test.py"),
        )
    )

    assert selected == (Path("tests/a_test.py"), Path("tests/z_test.py"))


def test_parser_requires_base_and_defaults_head() -> None:
    args = quality_gate.build_parser().parse_args(["--base", "baseline-sha"])

    assert args.base == "baseline-sha"
    assert args.head == "HEAD"
