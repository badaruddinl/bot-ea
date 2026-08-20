from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOTS = frozenset({"scripts", "src", "tests"})
EXTRACTED_RULE_TESTS = (
    "tests/gold_engine_core/test_bear_incremental.py",
    "tests/gold_engine_core/test_revised_restart.py",
    "tests/test_goldm_revised.py",
    "tests/test_goldm_revised_runtime.py",
    "tests/test_goldm_revised_stop_paths.py",
    "tests/test_goldm_revised_management.py",
    "tests/test_goldm_revised_risk.py",
    "tests/test_goldm_revised_trailing.py",
    "tests/test_goldm_bear_standalone.py",
    "tests/test_goldm_bear_v4.py",
    "tests/test_goldm_bear_replay.py",
    "tests/test_goldm_confluence.py",
)


def _run(
    command: Sequence[str],
    *,
    capture: bool = False,
    environment: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        text=True,
        capture_output=capture,
        env=environment,
    )


def _git(*arguments: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    safe_directory = REPOSITORY_ROOT.as_posix()
    return _run(
        ["git", "-c", f"safe.directory={safe_directory}", *arguments],
        capture=capture,
    )


def _tracked_changed_paths(base: str, head: str) -> tuple[Path, ...]:
    _git("cat-file", "-e", f"{base}^{{commit}}")
    _git("cat-file", "-e", f"{head}^{{commit}}")
    merge_base = _git("merge-base", base, head, capture=True).stdout.strip()
    if not merge_base:
        raise RuntimeError(f"no merge base between {base!r} and {head!r}")

    output = _git(
        "diff",
        "--name-only",
        "--diff-filter=ACMR",
        "-z",
        f"{merge_base}...{head}",
        capture=True,
    ).stdout
    return tuple(Path(value) for value in output.split("\0") if value)


def _quality_python_files(paths: Sequence[Path]) -> tuple[Path, ...]:
    selected: list[Path] = []
    for relative in paths:
        if relative.suffix != ".py" or not relative.parts:
            continue
        if relative.parts[0] not in QUALITY_ROOTS:
            continue
        absolute = (REPOSITORY_ROOT / relative).resolve()
        try:
            absolute.relative_to(REPOSITORY_ROOT)
        except ValueError as exc:
            raise RuntimeError(f"changed path escapes repository: {relative}") from exc
        if absolute.is_file():
            selected.append(relative)
    return tuple(sorted(set(selected), key=lambda value: value.as_posix()))


def _run_changed_file_checks(files: Sequence[Path]) -> None:
    if not files:
        print("quality_python_files=0")
        return

    values = [path.as_posix() for path in files]
    print(f"quality_python_files={len(values)}")
    _run([sys.executable, "-m", "ruff", "format", "--check", *values])
    _run([sys.executable, "-m", "ruff", "check", *values])

    source_files = [value for value in values if value.startswith("src/")]
    if source_files:
        _run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--follow-imports=skip",
                *source_files,
            ]
        )
    else:
        print("mypy_source_files=0")


def _run_core_coverage() -> None:
    package = REPOSITORY_ROOT / "src" / "gold_engine_core"
    if not package.is_dir():
        print("core_coverage=NOT_APPLICABLE_PRE_G03")
        return

    tests = REPOSITORY_ROOT / "tests" / "gold_engine_core"
    if not tests.is_dir():
        raise RuntimeError("gold_engine_core exists without tests/gold_engine_core")
    with tempfile.TemporaryDirectory(prefix="bot-ea-quality-") as temporary_root:
        pytest_temp = Path(temporary_root) / "pytest"
        environment = os.environ.copy()
        environment["COVERAGE_FILE"] = str(Path(temporary_root) / ".coverage-core")
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"--basetemp={pytest_temp.as_posix()}",
                "--cov=gold_engine_core.contracts",
                "--cov=gold_engine_core.corpus",
                "--cov=gold_engine_core.current_behavior",
                "--cov=gold_engine_core.profile",
                "--cov=gold_engine_core.reference_runtime",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-fail-under=90",
                tests.as_posix(),
            ],
            environment=environment,
        )
        rules = REPOSITORY_ROOT / "src" / "gold_engine_core" / "rules"
        if not rules.is_dir():
            return
        missing = [
            value for value in EXTRACTED_RULE_TESTS if not (REPOSITORY_ROOT / value).is_file()
        ]
        if missing:
            raise RuntimeError(f"missing extracted-rule tests: {', '.join(missing)}")
        rule_environment = os.environ.copy()
        rule_environment["COVERAGE_FILE"] = str(Path(temporary_root) / ".coverage-rules")
        _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                f"--basetemp={(Path(temporary_root) / 'pytest-rules').as_posix()}",
                "--cov=gold_engine_core.rules",
                "--cov-branch",
                "--cov-report=term-missing",
                "--cov-fail-under=75",
                *EXTRACTED_RULE_TESTS,
            ],
            environment=rule_environment,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run incremental goal quality gates.")
    parser.add_argument("--base", required=True, help="Audited comparison commit or ref.")
    parser.add_argument("--head", default="HEAD", help="Commit/ref to validate.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    changed = _tracked_changed_paths(args.base, args.head)
    _run_changed_file_checks(_quality_python_files(changed))
    _run_core_coverage()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
