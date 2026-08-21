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
| G10A | IN_PROGRESS | GOLDI, GOLDM, CROSS_PROFILE | `evidence/G10-reference-live-validation/` | GOLDm REAL read-only probe passed with zero order calls; GOLD.i dedicated terminal path and concurrent isolation evidence remain. |
| G10B | IN_PROGRESS | GOLDI | `evidence/G10-reference-live-validation/` | GOLD.i guarded DEMO lifecycle remains required after the second terminal is isolated. |
| G10C | DEFERRED_TO_G15 | GOLDM | `evidence/G10-reference-live-validation/` | GOLDm execution evidence uses the profile-locked binary in isolated Strategy Tester, never live REAL engineering orders. |
| G10D | PASS | SHARED | `evidence/G10D-remove-app-surfaces/` | Desktop UI, application runtime, WebSocket service, dependencies, launchers, tests, and stale docs were removed; fast and release suites passed. |
| G11 | PASS | SHARED, GOLDI, GOLDM, CROSS_PROFILE | `evidence/G11-mql5-runtime-skeleton/` | Profile-locked strict binaries compile with zero errors/warnings; scheduler, warm-up, identity failure, bounded tick path, and no-order invariants passed. |
| G12S | PASS | GOLDI, GOLDM, CROSS_PROFILE | `evidence/G12S-sizing-contract/` | User-authorized adaptive balance tiers were propagated through canonical manifests, final/validation configs, Python/MQL5 resolvers, regenerated fingerprints/corpora, and full fast/slow regression. |
| G12 | PASS | SHARED, GOLDI, GOLDM, CROSS_PROFILE | `evidence/G12-revised-parity/` | Native Revised decision/runtime and setup/restart parity certified on GOLD.i/XMGlobal-MT5 5 and GOLDm/XMGlobal-MT5 14. Exact state/reason/timestamps and one-tick geometry passed; compile, fast/slow regression, profile isolation, hashes, and disabled REAL authority verified. |
| G13 | PASS | SHARED, GOLDI, GOLDM | `evidence/G13-bear-parity/` | Incremental Bear state, M15 confluence, persistence/restart, exact event/reason/geometry parity, warning-clean compile, GOLD.i and GOLDm Strategy Tester, 685 fast tests, 154 slow tests, and quality gate are certified with REAL authority disabled. |

Raw or large evidence is stored outside Git under:

`E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e`

Every external artifact is referenced by SHA-256 from its gate summary.
