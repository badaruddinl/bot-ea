# G08 Execution Validity

Status: **IN_PROGRESS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. REAL authority remains disabled.

## Immutable executable plan

`SignalPlan` now carries profile/version/fingerprint, strategy/version/component, setup/signal IDs, setup-created/entry-ready/expiry times, side/symbol, planned entry/stop/target/risk/invalidation, spread/drift/tick contracts, volume, account/server/mode/terminal ownership, magic, and reason.

Worker plan construction freezes account binding, adaptive lot, policy version, and tick-normalized structural geometry before execution.

## Versioned execution policies

| Profile | Max drift | Max spread | TTL | Policy SHA-256 |
|---|---:|---:|---:|---|
| GOLDI | `0.15R` | `0.60` | 60 s | `363f816abb0c3aaad8f42cbd1905f2a29f8fd4342e60431a7b3d4ae54f1756b6` |
| GOLDM | `0.15R` | `0.72` | 60 s | `8ba3118bf79c5146334f28a06f058dde0ca83efe19be767176dd7fb5f8b8de5f` |

Policies bind the exact G01 profile fingerprint. Swapping GOLDI/GOLDM policy or profile config fails closed. GOLDM engineering DEMO requires an explicit context flag; it does not authorize REAL.

## Pre-send validation

The pure guard checks profile/config fingerprint, age, drift, spread, invalidation, account, server/mode, terminal, symbol, magic, position count, total volume, free margin, broker tick/volume/stops/freeze/trade constraints, duplicate signal, executable geometry, and broker check result.

Drift is exactly:

```text
abs(executable_quote - planned_entry) / planned_risk
```

The MT5 session performs read-only margin calculation, pure preflight, broker `order_check`, pure final validation, then an immediate account-binding recheck before `order_send`.

## No quote chasing

The executable quote becomes only the request price. Request SL/TP are the immutable `planned_stop` and `planned_target`; they are never translated by quote distance. If the current quote invalidates geometry, the order is rejected.

Integration tests verify stale, drift, broker-check reject, and duplicate plans produce no `order_send`; an accepted GOLDI/GOLDM request preserves exact planned SL/TP.

## Focused verification

```text
ruff format/lint: PASS
mypy: PASS
pure execution + contract + portfolio suite: 32 passed
session reject/send integration: 3 passed
worker-owned plan per profile: 2 passed
new-core suite: 77 passed
new-core branch coverage: 92.37%
execution.py coverage: 88%
core_coverage_xml_sha256=fcc2e7808b66fcfb78e4ad1cace286038760b6c0a253d793c4fa79b39e40546a
```

Quality-gate E2E and full regression remain required before G08 becomes PASS.
