# G16 Event Outbox, Database, and Telegram

Status: **IN_PROGRESS**

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

REAL orders: **DISABLED**
