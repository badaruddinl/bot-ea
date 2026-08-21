# G16 Event Outbox, Database, and Telegram

Status: **PASS**

Locked scope:

- EA emits transition events only, never per tick;
- append-only profile-specific spool with deterministic event IDs;
- bridge ingest is at-least-once and SQLite enforces `UNIQUE(event_id)`;
- ACK advances only after durable persistence/delivery state;
- GOLDI allowed final events route to `goldi_approved`; GOLDM always routes to
  `admin_only`;
- WATCH remains internal and does not create Telegram noise;
- bridge, DB, or Telegram failure never blocks the EA decision/order path;
- production REAL order authority remains **DISABLED**.

Current sub-batch:

- defining versioned event schema and bounded append-only MQL5 writer;
- building deterministic Python spool parser, SQLite ingest, delivery state,
  and audience policy with restart/idempotence tests.
- native MQL5 writer is profile-specific, append-only, shared-readable, and
  transition-only; runtime maps start/profile/entry/order/position/error/
  recovery transitions without writing on every tick.
- native Strategy Tester outbox proof PASS with correct GOLDI approved and
  GOLDM admin audiences, 100.00 USD unchanged balance, no mutation, and raw log
  SHA-256 `5ffdcff714fd427e87cd1f198a21b4402846f14eda2ce1830877451d7b3bc174`.
- Python bridge persists spool data and ACK offset in one transaction, rejects
  incomplete tails, quarantines invalid lines, deduplicates replay, and tracks
  recipient-level delivery/retry state.
- sender-only Telegram runtime loads approved GOLDI subscribers, never polls,
  suppresses WATCH noise, and cannot expose GOLDM to subscribers.
- final compile: GOLDI, GOLDM, and harness 0 errors/0 warnings.
- full regression PASS: 820 fast and 218 slow tests.
- quality gate PASS: Ruff/mypy, 90.12% safety-core coverage, 82.66% changed-rule
  coverage.

Final certification:

- DB/Telegram failure cannot block EA;
- backlog replay creates no duplicate row;
- profile/audience leakage tests all PASS.

REAL orders: **DISABLED**
