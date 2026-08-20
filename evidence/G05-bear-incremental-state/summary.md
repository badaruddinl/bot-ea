# G05 Bear Incremental State Machine

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM. REAL authority remains disabled.

## Incremental flow

The pure Bear machine now uses explicit immutable state:

```text
IDLE → WATCH_H1 → WATCH_M5 → WATCH_M1 → ENTRY_READY
```

Terminal rejection/expiry is represented by `CANCELLED`, then consumed on the next distinct closed bar. State carries profile/setup identity, setup time, level, entry zone, invalidation, touch/rejection/acceptance evidence, per-timeframe processed cursors, bounded buffers, arm evidence, and exact entry geometry.

The machine:

- accepts each M1/M5/M15/H1 bar at most once;
- rejects out-of-order direct input;
- processes equal close times in deterministic H1/M5/M1/M15 order;
- retains only bounded timeframe buffers;
- suppresses stale warm-up signals while recovering active watches;
- rejects profile/symbol/tick-size crossover.

## Live worker migration

`CompositePortfolioWorker._evaluate_bear()` no longer calls `BearMultiTimeframeReplay.run()` and no longer reads a 30-day history. It reads only `maximum_warmup_span`, feeds only bars newer than the stored cursors, and converts a newly emitted incremental signal/watch into the existing worker contract.

The historical replay remains the reference implementation and is not deleted.

## Replay parity

For both GOLDI (`spread_floor=0.20`) and GOLDM (`spread_floor=0.24`), deterministic fixtures are evaluated by full `BearMultiTimeframeReplay.run()` and by bar-by-bar incremental feed. Assertions require:

- identical entry, stop, and target;
- zero tick difference (stricter than the one-tick allowance);
- identical H1 accept, M5 arm, M1 ready stage path;
- profile-specific signal/setup IDs and no crossover;
- identical M5 touch/rejection evidence.

Additional tests cover H1 rejection, M5 acceptance, M1 expiry, bounded watch recovery, duplicate/out-of-order bars, buffer limits, and live-path replay prohibition.

## Focused verification

```text
ruff format/lint: PASS
mypy: PASS (incremental machine, worker, quality tooling)
focused worker/incremental/quality tests: 25 passed
replay parity and state tests: 8 passed
extracted rule suite with incremental tests: 99 passed
rule branch coverage: 82.67% (fail-closed threshold 75%)
rule_coverage_xml_sha256=bda6231d99d776f39e4d68efd5f26ed29f84ced6f82a5cc2e4fac8a702e6ab13
```

## Final verification

```text
python scripts/quality_gate.py --base ed5a88f2c19fc60054adba7cba0b183c13a28291 --head HEAD
exit=0
quality_python_files=5
ruff_format=PASS
ruff_lint=PASS
mypy=PASS (incremental machine, worker, quality tooling)
new_core=49 passed, 91.77%
extracted_and_incremental_rules=99 passed, 82.67%

python -m pytest -q --basetemp=<external>/G05-bear-incremental-state/full-pytest-temp --junitxml=<external>/G05-bear-incremental-state/full-pytest-junit.xml
exit=0
result=769 passed, 2 skipped, 2 warnings, 141 subtests passed
junit_tests=912
junit_failures=0
junit_errors=0
junit_sha256=52244be19493e3e3e5ab7b073ffaf3ead051684ecd24d43f4356055e6c4872d0
```

No strategy parameter, terminal, account, or order authority was changed. The production REAL profile remained disabled throughout G05.
