from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
QUALITY_ROOTS = frozenset({"scripts", "src", "tests"})


def _run(command: Sequence[str], *, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        check=True,
        text=True,
        capture_output=capture,
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
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--cov=gold_engine_core",
            "--cov-branch",
            "--cov-report=term-missing",
            "--cov-fail-under=90",
            tests.as_posix(),
        ]
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
