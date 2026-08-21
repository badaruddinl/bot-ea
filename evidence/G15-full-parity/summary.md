# G15 Full Parity Certification

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remained **DISABLED**.

## Certified matrix

- Pipelines: Python replay, Python incremental, MQL5 harness, and MT5 Strategy
  Tester.
- Exact fields: profile, event ID, setup ID, version, state, side, reason,
  semantic time, planned prices, and management action.
- Revised parity: 100% event/state/reason for 5 decision and 6 setup cases per
  profile.
- Bear parity: 100% event/state/reason for 5 cases per profile plus the locked
  two-profile M15 broker oracle.
- Planned-price tolerance: maximum one profile tick; observed corpus delta zero
  ticks.
- Management actions: OPEN, MODIFY, RESTART_RECOVER, CLOSE.
- Cross-profile event count: zero; GOLDI/GOLDM fingerprints are distinct and
  every corpus/report/native proof is profile-bound.
- Equity curves remain supplementary evidence only.

Canonical certification SHA-256:
`0bab8cd838ffa9d78c1e6b36e29637693568c9f1d25668680086d1b887fc2e23`.

## Dual-profile Strategy Tester lifecycle

| Profile | Symbol/server | Result | Retcodes | Final balance | Raw log SHA-256 |
| --- | --- | --- | --- | --- | --- |
| GOLDI | `GOLD.i#` / `XMGlobal-MT5 5` | PASS | open/modify/close `10009` | 99.50 USD | `8393ac9f0b8bcbc333281ddac507dc388cfc7c7474e20f49ed5ca0976c602f6e` |
| GOLDM | `GOLDm#` / `XMGlobal-MT5 14` | PASS | open/modify/close `10009` | 99.68 USD | `5c96c516fff256271343c993b1a4b8d8c44c20270f12064f175d9c59b8820e7d` |

Both were isolated Strategy Tester simulations. GOLDM tester used a dedicated
`MQL_TESTER`-only interlock; the production runtime cannot set or use that
override. Balance differences are simulated spread from immediate round trips.

## Build and regression

- MetaEditor 6090: GOLDI, GOLDM, and both lifecycle harnesses compiled with 0
  errors and 0 warnings.
- Final profile binary SHA-256: GOLDI
  `3f272b5548f37a4d724d1443cdf0ce6772ffc362f9f72cab2240c39f2b95a34a`,
  GOLDM
  `e11686f30c2df88cfaa74c936dbefd716c1d0ffd7c16a5edc7c795c5f8a7af98`.
- Fast regression: 805 passed; slow regression: 218 passed.
- Quality gate: PASS; Ruff clean, safety core 90.12%, changed strategy rules
  82.66%.
- The verifier detected and corrected one stale G12 corpus-hash pointer caused
  by the already-certified sizing regeneration; no strategy or corpus value was
  changed.
- External raw evidence, binaries, compile logs, and JUnit:
  `E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G15-full-parity\final`.
- External `SHA256SUMS` SHA-256:
  `84e700841a1789272df4153e59c0bd2ee70b9b89f76470715d8a02918c8ac8dc`.

REAL orders: **DISABLED**
