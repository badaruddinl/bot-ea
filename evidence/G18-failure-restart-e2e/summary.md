# G18 Failure and Restart E2E

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remained **DISABLED**.

## Certified behavior

- Bridge, DB, Telegram, backlog, and replay failures recover without changing
  EA decision or order authority.
- Broker reject, ambiguous result, Algo-off, market-closed, ownership, manual
  intervention, duplicate EA, and magic-collision paths fail closed.
- Revised and Bear restart corpora, one-profile isolation, dual-terminal
  process restart, and open-position recovery passed.
- An actual Windows Server VM boot cycle changed the OS boot ID. GOLDI and
  GOLDM recovered with exact profile/account/server bindings, new runtime
  identities, and post-boot heartbeats.
- No duplicate order, lost ownership, or cross-profile management was found.

## Verification

```text
strict G18 verifier: PASS
fast regression: 776 passed, 154 deselected, 77 subtests
slow regression: 154 passed, 776 deselected, 64 subtests
quality core: 130 passed, 90.12%
quality strategy rules: 108 passed, 82.66%
GOLDI process probe compile: 0 errors, 0 warnings
GOLDM process probe compile: 0 errors, 0 warnings
```

The VM run exposed and fixed two evidence-tooling defects: Windows Server 2019
path API compatibility and the invalid assumption that MT5 `ChartID()` changes
across profile recovery. The final probe uses a per-runtime identity while
retaining ChartID as diagnostic context.

REAL orders: **DISABLED**
