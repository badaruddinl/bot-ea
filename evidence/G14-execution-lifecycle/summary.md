# G14 EA Execution and Position Lifecycle

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remained **DISABLED**.

## Certified behavior

- The MQL5 execution guard implements the complete 18-reason Python reference
  matrix before mutation and preserves structural entry, SL, TP, and
  invalidation geometry.
- Broker preflight binds account, server, trade mode, terminal identity,
  symbol, magic, profile fingerprint, volume, margin, filling, stops/freeze,
  exposure, signal age/drift, spread, duplicate identity, and `OrderCheck`.
- `CTrade` mutation is synchronous and structurally below a disabled-by-default
  authority interlock. Retcodes, order/deal receipts, modify, and close are
  handled explicitly.
- Python production workers no longer contain `order_send`, `order_check`, or
  `order_calc_margin`; every final/validation profile declares authority as
  `mql5` or `disabled`, and the loader rejects `python` authority.
- Position ownership is symbol/magic/profile-comment scoped. Runtime refuses a
  second position, multiple/foreign/unowned positions, missing or corrupt
  ownership state, and manual volume/entry/SL/TP changes.
- Expected position geometry uses two alternating, checksum-protected,
  profile-fingerprint-bound persistent slots. Restart loads the newest valid
  slot and falls back to the previous slot if the newest is corrupt.
- Runtime saves state after entry/modify, clears it after close, reconstructs
  open positions after restart, and disables authority on ambiguity.

## Native Strategy Tester

| Proof | Profile coverage | Result | Final balance | Raw log SHA-256 |
| --- | --- | --- | --- | --- |
| Execution guard | GOLDI + GOLDM policy matrix | PASS | 100.00 USD | `d01e11ce0d8e243a8a5d10f152b301c5794217c6a802216f08f83a9eab2afd82` |
| Broker preflight | GOLDI + GOLDM policy matrix | PASS | 100.00 USD | `78bec146371ba61d334bda424b022653cbd99cb87ca75e04f29865f0c5a35a57` |
| Disabled authority | GOLDI + GOLDM shared path | PASS | 100.00 USD | `7ecddc4667e08f589a073203a2480f85408cedab13a5d703566481813c5658a3` |
| Open/modify/restart/close | GOLDI DEMO tester | PASS | 99.62 USD | `969db269a0d8f1f6b363758a83da3198735d50f3dac143e1f9a9c884bbe4744e` |
| Persistent ownership/manual change | GOLDI + GOLDM shared path | PASS | 100.00 USD | `036b94866b39419c58d4d0d3ee8775679951ff2e08e9dc6fd1c28f0e789c7382` |

The 99.62 USD lifecycle balance is the expected simulated spread cost of an
immediate tester-only open/close round trip. No external account was touched.
GOLDM has no broker-provided safe DEMO mirror, so no GOLDM order mutation was
attempted; its profile-specific binary and shared execution contracts were
compiled and tested without enabling REAL authority.

## Compile, tests, and evidence

- MetaEditor 6090: GOLDI, GOLDM, and persistence harness all compiled with 0
  errors and 0 warnings.
- Binary SHA-256: GOLDI
  `081d18a5a46d30a29d250c4413b4f069a7ef1be820bfaccbed2af08b1521556e`,
  GOLDM
  `b39e9ad28a0222611b226a516e63288105f5726e7afa3593400dd6554e61a7e0`,
  persistence harness
  `3609a0fd282a6dcab58ffb9a66508ef7fa22d9bcc3837dc3dfd1439426bfa225`.
- Fast regression: 795 passed; slow regression: 218 passed.
- Incremental quality gate: PASS; Ruff and mypy clean, safety core 90.12%,
  changed strategy rules 82.66%.
- External raw evidence and binaries:
  `E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G14-execution-lifecycle\final`.
- External `SHA256SUMS` SHA-256:
  `8d0f3b78e3798a5fe09380a6803bb6e46a7e6e3f8a99061ea08f7f1449f12db7`.

REAL orders: **DISABLED**
