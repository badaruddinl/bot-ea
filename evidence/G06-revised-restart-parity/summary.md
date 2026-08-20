# G06 Revised Restart Parity

Status: **IN_PROGRESS**

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

Quality-gate E2E and full regression remain required before G06 becomes PASS.
