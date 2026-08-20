# G02 Current-Behavior Corpus

Status: **IN_PROGRESS**

Scope: GOLDI and GOLDM current Python semantics. REAL order authority remains disabled.

## Immutable corpus

| Profile | Records | Corpus SHA-256 |
|---|---:|---|
| GOLDI | 34 | `73df973f03258b3f96c52a22103bf1c5a98467ee9416a4a786cc789bf01f4106` |
| GOLDM | 34 | `bc4450049bc8d1d370a229dd9509220ee8adf46ea822c343e0868b377b63da70` |

Each record contains profile and input fingerprints, a fixed offset-aware semantic `available_at`, profile-namespaced setup ID, causal state transitions, decision, planned geometry, reason, execution outcome, source reference, and source SHA-256. Strategy records require closed bars.

The generator binds every scenario to an existing source assertion or current implementation symbol. Rebuilding into a second directory must produce byte-identical JSONL and sidecars. GOLDI and GOLDM can never share a corpus file.

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
GOLDI=73df973f03258b3f96c52a22103bf1c5a98467ee9416a4a786cc789bf01f4106
GOLDM=bc4450049bc8d1d370a229dd9509220ee8adf46ea822c343e0868b377b63da70

python -m pytest -q --basetemp=<external>/G02-current-behavior-corpus/pytest-temp-run4 --cov=gold_engine_core --cov-branch --cov-report=term-missing --cov-report=xml:<external>/G02-current-behavior-corpus/coverage-run4.xml --cov-fail-under=90 tests/gold_engine_core
exit=0
result=27 passed
branch_coverage=93.62%
coverage_xml_sha256=c914e28459f54de09b133d1b812236d5ae8b363185ae212aaf6bfbe206d700e7
```

Quality-gate E2E and full regression are still required before G02 becomes PASS.
