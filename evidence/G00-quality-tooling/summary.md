# G00-Q Quality Tooling

Scope: SHARED tooling only. No strategy, risk, execution, profile, or runtime semantics are changed.

Status: **PASS**

## Pinned tools

- Ruff `0.16.3`
- mypy `2.3.1`
- pytest `9.1.1`
- pytest-cov `7.1.0`

Versions were resolved from the package index on 2026-08-20 and are exact pins in the `dev` extra.

## Ratchet policy

- Ruff format and lint apply to every committed Python file added or changed under `scripts/`, `src/`, or `tests/` relative to the audited comparison commit.
- Mypy strict mode applies to changed source files. Imports are skipped at legacy boundaries so unchanged historical debt is not falsely attributed to a focused change.
- Once `src/gold_engine_core/` exists, `tests/gold_engine_core/` becomes mandatory and branch coverage below 90% fails the gate.
- A malformed/missing Git ref, tool failure, missing core tests, lint/type error, coverage failure, or test failure returns non-zero.

## Baseline debt observed, not waived

Exploratory whole-repository runs found 129 files requiring Ruff formatting and 116 mypy errors across selected legacy/transitive modules. This batch does not bulk-reformat or globally suppress those findings. The changed-file ratchet prevents new goal code from adding to that debt.

## Focused verification

```text
python -m ruff format --check scripts/quality_gate.py tests/test_quality_gate.py
exit=0

python -m ruff check scripts/quality_gate.py tests/test_quality_gate.py
exit=0

python -m mypy --follow-imports=skip scripts/quality_gate.py
exit=0

python -m pytest -q --basetemp=<external>/quality-tooling/pytest-temp2 tests/test_quality_gate.py
exit=0; 3 passed

python -m pip install --disable-pip-version-check --dry-run -e ".[dev]"
exit=0
```

## Final verification

```text
python scripts/quality_gate.py --base 1cd5df979230e5fe4e737fe470cf278ece3951af --head HEAD
exit=0
quality_python_files=3
ruff_format=PASS
ruff_lint=PASS
mypy_source_files=0
core_coverage=NOT_APPLICABLE_PRE_G03

python -m pytest -q --basetemp=<external>/quality-tooling/full-pytest-temp-run2 --junitxml=<external>/quality-tooling/full-pytest-junit-run2.xml
exit=0
result=719 passed, 2 skipped, 2 warnings, 141 subtests passed
junit_sha256=b3f70c5959b3f93ad6bc3cf0cc6a0c28fb942b0b6b528736ace1866defb7cf16
```

The first full run correctly failed because the legacy CI contract still required `unittest discover`; its JUnit SHA-256 is `e90d75fba249e58d514577910472e0b4149e646fb046348708959be54bc11f9d`. The contract was updated to require full pytest, isolated basetemp, JUnit evidence, and the incremental quality command. The authoritative rerun passed.
