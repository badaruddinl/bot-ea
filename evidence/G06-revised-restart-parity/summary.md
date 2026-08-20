# G06 Revised Restart Parity

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM. REAL authority remains disabled.

## Durable detector checkpoint

`RevisedSetupDetector` now exports/restores a strict immutable checkpoint containing:

- maximum M1 watch window;
- active BUY/SELL setup and original causal trigger;
- reinforced pattern/votes/level/invalidation;
- pending terminal reason;
- last classified closed M5 bar;
- latest consumed trigger per side.

The checkpoint has a strict JSON boundary, offset-aware timestamps, finite numeric values, unique side ownership, and exact window validation in the worker.

Warm-up ignores M5 bars older than/equal to the restored classification cursor. A consumed trigger is retained and blocks the same or older setup from being resurrected, while a genuinely newer setup remains eligible.

## Restart matrix

Deterministic tests checkpoint and reconstruct a new detector at:

- before setup;
- after M5 setup;
- after same-side reinforcement;
- during the M1 watch window;
- immediately before an entry-ready decision;
- after expiry and opposite cancellation;
- after a consumed entry with an open position.

Assertions require the same setup object/ID/trigger and decision payload, one-shot terminal delivery, no duplicate, no lost setup, and no stale historical resurrection.

Worker persistence stores detector state atomically alongside existing `seen` IDs and tracked open positions. Restart is tested separately against GOLDI and GOLDM state namespaces; no terminal or order API is called.

## Focused verification

```text
ruff format/lint: PASS
mypy: PASS
restart + Revised + worker + quality focused suite: 59 passed
restart-specific matrix: 7 passed (including both profiles)
extracted-rule suite: 106 passed
rule branch coverage: 82.62%
rule_coverage_xml_sha256=3cd98a0e14e273709b9c568832c7b0d515e04d97e2ffc45ab6c065dc6f923b12
```

## Final verification

```text
python scripts/quality_gate.py --base 0d1dbe97f4682ce268b5001537a9751c0f22460d --head HEAD
exit=0
quality_python_files=6
ruff_format=PASS
ruff_lint=PASS
mypy=PASS (4 changed source files)
new_core=56 passed, 91.77%
rule_and_restart_suite=106 passed, 82.66%

python -m pytest -q --basetemp=<external>/G06-revised-restart-parity/full-pytest-temp --junitxml=<external>/G06-revised-restart-parity/full-pytest-junit.xml
exit=0
result=777 passed, 1 skipped, 2 warnings, 141 subtests passed
junit_tests=919
junit_failures=0
junit_errors=0
junit_sha256=5d841b54590824bd7a8370dee715943f6ccded0839a931597d9909871ec91053
```

No terminal, account, or order API was used. The production REAL profile remained disabled throughout G06.
