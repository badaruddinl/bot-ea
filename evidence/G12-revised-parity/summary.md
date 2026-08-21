# G12 Revised MQL5 Parity

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remained **DISABLED**.

## Certified behavior

- Python/MQL5 decision event and state parity: 100% for the locked corpus.
- Reason strings: exact.
- M5 setup and semantic trigger timestamps: exact.
- Entry, SL, TP, obstacle, and R geometry: within one profile tick (`0.01`).
- BUY and observation-only SELL Revised decisions are symmetric where required.
- Setup acceptance, reinforcement without trigger reset, restart restore,
  consumed no-resurrection, expiry, and opposite cancellation are exact.
- The harness contains no `OrderSend`, `CTrade`, network, or order authority.

## Native Strategy Tester

| Profile | Symbol | Server | Result | Tick/bar count | Final tester balance | Raw log SHA-256 |
| --- | --- | --- | --- | --- | --- | --- |
| GOLDI | `GOLD.i#` | `XMGlobal-MT5 5` | PASS | 1 / 1 | 100.00 USD | `33667f5797811cde14be546a579bda7d316d4de37386db7efb68a3a7f86e6d8d` |
| GOLDM | `GOLDm#` | `XMGlobal-MT5 14` | PASS | 1 / 1 | 100.00 USD | `001b71107332b6451cd24f4349e71667918726f6cfb1708dcebe3ee7b39e103a` |

Both runs reported all ten decision/setup/restart assertions as `true`,
`OnTester result 1`, and no order/deal mutation.

## Hashes and tests

- Decision corpus (10 vectors):
  `7f458fb7e216553c97e50e20a9ec58094ffd38e88dd31cb74aca9e611c8476b4`.
- Setup/restart corpus (12 vectors):
  `34761b112834a968ad425a4c8b949a64c1fec0027f51721fc9f631d63a4b8610`.
- Compile evidence (MetaEditor 6090, both EA binaries plus harness, all 0 errors
  and 0 warnings):
  `be144b86f75a8175f9ec6046b11f7e02a2420f5eb422472d8c94a3dcbce8fde1`.
- Final parity evidence:
  `96bb599489580c723372d87322112485df654adf47f33dddaaa9a753921b7c52`.
- Fast regression: 663 passed, 154 deselected, 77 subtests.
- Slow regression: 154 passed, 663 deselected, 64 subtests.
- Incremental quality gate: PASS; core 90.12%, strategy rules 82.66%.

## Evidence storage

Git stores manifests, summaries, checksums, and verifier output. Raw logs are
stored externally at:

`E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G12-revised-parity\final`

REAL orders: **DISABLED**
