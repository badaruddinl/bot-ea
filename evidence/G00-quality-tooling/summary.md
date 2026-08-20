# G00-Q Quality Tooling

Scope: SHARED tooling only. No strategy, risk, execution, profile, or runtime semantics are changed.

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

End-to-end changed-file execution and the full regression suite are recorded before this batch is marked PASS.
