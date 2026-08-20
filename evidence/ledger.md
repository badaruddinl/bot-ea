# BOT-EA-CODEX-GOAL Evidence Ledger

Goal: `BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E`

Baseline: `b042d51cfc3b2ea1f9aa048054af03d79d79726e`

REAL order authority: **DISABLED**

| Gate | Status | Scope | Evidence | Notes |
|---|---|---|---|---|
| G00 | PASS | SHARED, GOLDI, GOLDM, CROSS_PROFILE | `evidence/G00-baseline/` | Exact baseline is reproducible; fresh suite passed. Missing external prerequisites remain explicit and block only dependent later gates. |
| G00-Q | PASS | SHARED | `evidence/G00-quality-tooling/` | Pinned incremental quality ratchet and full regression passed; core coverage activates fail-closed at G03. |
| G01-G21 | NOT_STARTED | — | — | No engine implementation starts before G00 review. |

Raw or large evidence is stored outside Git under:

`E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e`

Every external artifact is referenced by SHA-256 from its gate summary.
