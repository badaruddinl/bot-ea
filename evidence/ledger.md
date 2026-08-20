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
| G05 | IN_PROGRESS | SHARED, GOLDI, GOLDM | `evidence/G05-bear-incremental-state/` | Bear bar-by-bar state machine and bounded live-worker integration are under implementation. |
| G01-G21 | NOT_STARTED | — | — | No engine implementation starts before G00 review. |

Raw or large evidence is stored outside Git under:

`E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e`

Every external artifact is referenced by SHA-256 from its gate summary.
