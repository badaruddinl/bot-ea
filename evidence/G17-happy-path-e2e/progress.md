# G17 Full Happy-Path E2E

Status: **IN_PROGRESS**

Locked scope:

- GOLDI: actual DEMO terminal only; production order authority remains disabled
  until the explicit E2E run;
- GOLDM: isolated Strategy Tester only because the broker provides no safe
  GOLDm DEMO mirror; REAL mutation is prohibited;
- prove broker tick -> EA -> setup/confirmation -> guards -> order -> position
  -> close -> spool -> SQLite -> correctly routed Telegram sender;
- preserve exact profile/account/server/symbol/magic/audience identity;
- no Python order authority and no duplicate order/event/delivery.

Current sub-batch:

- constructing deterministic E2E harness/capture around the certified G15
  execution lifecycle and G16 event bridge;
- preparing GOLDI DEMO attachment/authority checklist without changing the
  terminal until preflight and rollback evidence are complete.

REAL orders: **DISABLED**
