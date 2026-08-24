# G13 Bear MQL5 Parity

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM. Production REAL order authority remained
**DISABLED**.

## Certified behavior

- Python/MQL5 Bear event, state, reason, timestamp, and geometry parity: 100%
  for the locked profile-symmetric corpus.
- Incremental state is bounded and causal:
  `IDLE -> WATCH_H1 -> WATCH_M5 -> WATCH_M1 -> ENTRY_READY`.
- H1 context, M15 resistance/support/Fibonacci/RSI/Stochastic/momentum scanner,
  M5 acceptance/rejection, and M1 confirmation match the Python reference.
- Duplicate/old bars are no-ops or fail closed; historical warm-up cannot
  promote an entry.
- Dual-slot profile-bound persistence, corruption rejection, stale recovery,
  cancellation, expiry, and restart/no-resurrection behavior are certified.
- The harness contains no `OrderSend`, `CTrade`, network, or order authority.

## Native Strategy Tester

| Profile | Symbol | Server | Result | Tick/bar count | Final tester balance | Raw log SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| GOLDI | `GOLD.i#` | `XMGlobal-MT5 5` | PASS | 1 / 1 | 100.00 USD | `bcbf25fe746186d5cc08d2229d2dc655fb364d137969030c99fe5f973cb7d380` |
| GOLDM | `GOLDm#` | `XMGlobal-MT5 14` | PASS | 1 / 1 | 100.00 USD | `ca4ed7769fc0c9483b724069495d638a9a9b0241d821c96fef564826ad0fbe34` |

Both runs reported every H1/M15/M5/M1, incremental, rejection, acceptance,
restart/expiry, and persistence assertion as `true`, `OnTester result 1`, and
no order/deal mutation.

## Hashes and tests

- Incremental Bear corpus (10 vectors):
  `fe0228da98a8f713dc69948d0bd9f34cc49e54928d264524c3a3a20ce6f27b01`.
- M15 broker oracle (two profile vectors, 50 bars each):
  `daf70b6762b024c6ec3c8032374797a2dc1a359c8cbca9dbee777681d0c8ff09`.
- Compile evidence (MetaEditor 6090, both profile binaries plus harness, all 0
  errors and 0 warnings):
  `76b700118415e59cd09ed411ccd56f361625ba0ae370ee9737b1acb0fd6257f3`.
- Final parity evidence:
  `96fdd9c8805e5fb984c70569473a8acaaa19c90ba2d4c3ba6889f137aab408d6`.
- Fast regression: 685 passed, 154 deselected.
- Slow regression: 154 passed, 685 deselected.
- Incremental quality gate: PASS; core 90.12%, strategy rules 82.66%.

## Evidence storage

Git stores manifests, summaries, checksums, and verifier output. Raw logs,
binaries, and JUnit XML are stored externally at:

`E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G13-bear-parity\final`

External `SHA256SUMS` SHA-256:
`8eee0c4da3877937e408a26bb687816d7c778517f92b7a533ce06d84fc676d1a`.

REAL orders: **DISABLED**
