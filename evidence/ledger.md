# BOT-EA-CODEX-GOAL Evidence Ledger

Goal: `BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E`

Baseline: `b042d51cfc3b2ea1f9aa048054af03d79d79726e`

REAL order authority: **DISABLED**

| Gate | Status | Scope | Evidence | Notes |
|---|---|---|---|---|
| G00 | PASS | SHARED, GOLDI, GOLDM, CROSS_PROFILE | `evidence/G00-baseline/` | Exact baseline is reproducible; fresh suite passed. Missing external prerequisites remain explicit and block only dependent later gates. |
| G00-Q | PASS | SHARED | `evidence/G00-quality-tooling/` | Pinned incremental quality ratchet and full regression passed; core coverage activates fail-closed at G03. |
| G01 | PASS | GOLDI, GOLDM, CROSS_PROFILE | `evidence/G01-profile-fingerprints/` | Immutable canonical manifests, component binding, profile isolation, mutation tests, quality gate, and full regression passed. |
| G02 | PASS | GOLDI, GOLDM | `evidence/G02-current-behavior-corpus/` | Deterministic causal profile-isolated corpus, current wrong behavior, restart records, quality gate, and full regression passed. |
| G03 | PASS | SHARED, CROSS_PROFILE | `evidence/G03-common-strategy-contract/` | Pure state-explicit contracts, causal/ownership guards, quality gate, and full regression passed. |
| G04 | PASS | SHARED, GOLDI, GOLDM | `evidence/G04-pure-rule-extraction/` | Revised/Bear pure rules, legacy identity, corpus stability, type/lint ratchets, quality gate, and full regression passed. |
| G05 | PASS | SHARED, GOLDI, GOLDM | `evidence/G05-bear-incremental-state/` | Bar-by-bar/replay parity, bounded recovery, live-worker migration, quality gate, and full regression passed. |
| G06 | PASS | SHARED, GOLDI, GOLDM | `evidence/G06-revised-restart-parity/` | Full restart matrix, stale-resurrection guards, dual-profile worker recovery, quality gate, and regression passed. |
| G07 | PASS | SHARED, GOLDI, GOLDM, CROSS_PROFILE | `evidence/G07-event-driven-reference-runtime/` | Fast/bar/slow lanes, deterministic sequence, outbox isolation, stall containment, quality gate, and regression passed. |
| G08 | PASS | SHARED, GOLDI, GOLDM, CROSS_PROFILE | `evidence/G08-execution-validity/` | Immutable plan/policy, all pre-send guards, no quote chasing, integration, quality gate, and regression passed. |
| G09 | PASS | SHARED, GOLDI, GOLDM | `evidence/G09-causal-tick-replay/` | Common-runtime replay, forming-bar exclusion, tick/same-bar policy, profile reports, quality gate, and regression passed. |
| G10 | BLOCKED | GOLDI, GOLDM, CROSS_PROFILE | `evidence/G10-reference-live-validation/` | Shared harness/preparation passed; actual dual-terminal DEMO evidence is unavailable because IDCloudHost remains unauthenticated and no safe-DEMO bindings are accessible. |
| G01-G21 | NOT_STARTED | — | — | No engine implementation starts before G00 review. |

Raw or large evidence is stored outside Git under:

`E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e`

Every external artifact is referenced by SHA-256 from its gate summary.
