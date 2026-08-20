# G07 Event-Driven Python Reference Runtime

Status: **IN_PROGRESS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. REAL authority remains disabled.

## Runtime lanes

### Fast lane

- accepts monotonic ticks;
- runs explicit profile tick guards;
- detects D1/H1/M15/M5/M1 bucket transitions;
- emits bounded closed-bar requests;
- fails closed when catch-up exceeds the configured limit.

It performs no persistence, reconciliation, notification, DB, network, or order work.

### Bar lane

- validates profile ownership and exact requested open/close time;
- processes each bar once using timeframe cursors;
- dispatches the state-explicit `PureStrategyEngine` interface;
- validates engine sequence/time/ownership invariants;
- writes decisions/events only to a bounded in-memory outbox.

Repeated identical bars are idempotent; older bars and cross-profile requests fail closed.

### Slow lane

Only this lane can call reconciliation, persistence, and notification ports. A sink failure leaves the complete in-memory outbox untouched for retry and cannot affect the engine state or create an order.

## Profile isolation

GOLDI and GOLDM use distinct profile configs, engine states, bucket/bar cursors, pending events, and event-ID namespaces. A daemon-isolated step runner returns the healthy profile result within its deadline while separately reporting failed or stalled profiles. A blocked GOLDM callback does not hold GOLDI.

## Determinism and safety

- Refeeding the same tick/bar sequence yields identical event order and IDs.
- Event IDs include profile, lane/type, timeframe, and semantic bar identity.
- Catch-up and outbox sizes are bounded.
- Runtime source contains no MT5, database, Telegram, HTTP, sleep, or order-send dependency.

## Focused verification

```text
reference runtime tests: 12 passed
ruff format/lint: PASS
mypy: PASS
new-core suite: 67 passed
new-core branch coverage: 93.37%
reference_runtime.py coverage: 98%
core_coverage_xml_sha256=53f7b7482c86f4093e55924ce494929fc21c675aaac810cfa6909cea3fd0c867
```

Quality-gate E2E and full regression remain required before G07 becomes PASS.
