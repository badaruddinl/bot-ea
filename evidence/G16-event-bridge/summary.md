# G16 Event Outbox, Database, and Telegram

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remained **DISABLED**.

## Certified behavior

- EA emits versioned JSON transition events to append-only, profile-specific
  Common Files spools. No spool write occurs on every tick.
- Event schema carries profile/version/fingerprint, event/setup/signal/order/
  position IDs, semantic server time, symbol, reason, audience, and payload.
- SQLite uses `event_id` as the primary key, WAL plus FULL synchronous mode,
  and commits event persistence with the acknowledged byte offset atomically.
- Incomplete trailing lines are not acknowledged. Invalid lines are durably
  quarantined before their offsets advance.
- Replaying a spool is at-least-once and creates no duplicate DB row.
- Delivery is recipient-idempotent. A Telegram failure persists RETRY state and
  retries only recipients that have not been delivered.
- GOLDI final entry/open/close may route to admins plus approved subscribers;
  GOLDM always routes to admins only. SETUP/WATCH events are persisted but
  suppressed from Telegram.
- Runtime is sender-only and never calls Telegram `getUpdates`.
- Bridge, SQLite, or Telegram failures are outside the EA decision/order path.

## Native and regression evidence

- Native outbox Strategy Tester PASS: GOLDI and GOLDM append true, profile
  audiences correct, `OnTester result 1`, final balance 100.00 USD, no
  order/deal mutation; raw log SHA-256
  `5ffdcff714fd427e87cd1f198a21b4402846f14eda2ce1830877451d7b3bc174`.
- MetaEditor 6090: GOLDI, GOLDM, and outbox harness all 0 errors and 0 warnings.
- Profile binary SHA-256: GOLDI
  `fd27f74862ed77dbb2750ab6704d5b30aa99058a944865bb5f52d6f6827b315c`,
  GOLDM
  `0ea04b78fa2b161110d3b719bb71f0ce9706421a2c112b2d7a3a4e3f636f7776`.
- Full regression: 820 fast and 218 slow tests passed.
- Quality gate: Ruff/mypy clean for changed code, safety core 90.12%, changed
  strategy rules 82.66%.
- External raw evidence/binaries:
  `E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G16-event-bridge\final`.
- External `SHA256SUMS` SHA-256:
  `e60f05b4e36333dc9eead2ed9dd054c272f3ec3b20f467edf79bca9e60e5887b`.

REAL orders: **DISABLED**
