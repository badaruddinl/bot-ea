# G02 Current-Behavior Corpus

Status: **PASS**

Scope: GOLDI and GOLDM current Python semantics. REAL order authority remains disabled.

## Immutable corpus

| Profile | Records | Corpus SHA-256 |
|---|---:|---|
| GOLDI | 34 | `74182e79084cbf3dbef9680e313cd7de8397c50df00ac7a5d6007c59a61471f1` |
| GOLDM | 34 | `0e3c5f5d3b898999115f2e601fb9e18f22bbc4af96b382fb3b263fec0598e58a` |

Each record contains profile and input fingerprints, a fixed offset-aware semantic `available_at`, profile-namespaced setup ID, causal state transitions, decision, planned geometry, reason, execution outcome, source reference, and source SHA-256. Strategy records require closed bars.

The generator captures every scenario's source assertion/implementation SHA in the immutable corpus. Later refactors reuse that captured oracle SHA when rebuilding the same scenario, so moving an implementation cannot silently redefine baseline input identity. A new or renamed scenario must resolve and hash a live source oracle. Rebuilding into a second directory must produce byte-identical JSONL and sidecars. GOLDI and GOLDM can never share a corpus file.

## Scenario coverage per profile

- Revised BUY: no setup, M5 setup, reinforcement, opposite cancellation, expiry, M1 range, M1 momentum, obstacle, psychological context, supply/demand context, entry ready, and restart.
- Bear SELL: M15 setup, H1 pass/reject, M5 touch, M5 rejection, M5 acceptance, M1 confirmation, expiry, entry ready, and restart.
- Execution: fresh/stale quote, drift, spread, invalidation, duplicate, max positions, lot normalization, wrong identity, broker check/send rejection, fill, and restart.

## Preserved current wrong behavior

This gate intentionally records rather than fixes these current semantics:

- `SignalPlan` has no `valid_until`;
- no immutable spread contract exists on `SignalPlan`;
- no invalidation field exists on `SignalPlan`;
- the current portfolio executor shifts structural SL/TP distances to the current quote;
- live Bear restart recomputes historical state instead of restoring an incremental state machine;
- Revised persistence exists, but full watch-point restart parity is not yet certified.

These defects are migration baselines for later gates and are not accepted as target behavior.

## Focused verification

```text
python -m ruff check src/gold_engine_core scripts/build-current-behavior-corpus.py tests/gold_engine_core
exit=0

python -m mypy --follow-imports=skip src/gold_engine_core
exit=0

python scripts/build-current-behavior-corpus.py
exit=0
GOLDI=74182e79084cbf3dbef9680e313cd7de8397c50df00ac7a5d6007c59a61471f1
GOLDM=0e3c5f5d3b898999115f2e601fb9e18f22bbc4af96b382fb3b263fec0598e58a

python -m pytest -q --basetemp=<external>/G02-current-behavior-corpus/pytest-temp-run4 --cov=gold_engine_core --cov-branch --cov-report=term-missing --cov-report=xml:<external>/G02-current-behavior-corpus/coverage-run4.xml --cov-fail-under=90 tests/gold_engine_core
exit=0
result=27 passed
branch_coverage=93.62%
coverage_xml_sha256=c914e28459f54de09b133d1b812236d5ae8b363185ae212aaf6bfbe206d700e7
```

## Final verification

```text
python scripts/quality_gate.py --base 24b77fa2c032d366326d2ef1b780df138041ab1c --head HEAD
exit=0
quality_python_files=5
ruff_format=PASS
ruff_lint=PASS
mypy=PASS (3 changed source files)
core_tests=27 passed
branch_coverage=93.62%

python -m pytest -q --basetemp=<external>/G02-current-behavior-corpus/full-pytest-temp --junitxml=<external>/G02-current-behavior-corpus/full-pytest-junit.xml
exit=0
result=748 passed, 1 skipped, 2 warnings, 141 subtests passed
junit_tests=890
junit_failures=0
junit_errors=0
junit_sha256=0bbd2b6f9a774ade57d836b3d4467e96efba5b4848d60c8153c10c0c8234e6b4
```

No engine rule, profile risk, terminal, worker, account, or order executor was changed or started. REAL authority remained disabled throughout G02.
