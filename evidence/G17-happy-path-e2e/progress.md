# G17 Full Happy-Path E2E

Status: **PASS**

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
- shared lifecycle harness now emits one correlated six-event chain:
  `SETUP_CREATED -> ENTRY_READY -> ORDER_SUBMITTED -> POSITION_OPENED ->
  POSITION_MODIFIED -> POSITION_CLOSED`, carrying setup, signal, order,
  position, event, and profile identity into the G16 spool.
- GOLDM isolated Strategy Tester chain PASS on `GOLDm#` / `XMGlobal-MT5 14`:
  magic `26081912`, all open/modify/close retcodes `10009`, six correlated
  events, positions `0 -> 0`, and no REAL mutation; raw log SHA-256
  `a5cca41620ab7286a4bf8dd47b0a70664f2ce1fcb43c85bc804d4f0cb7352614`.
- GOLDI actual DEMO chain PASS on account `108098316` / `XMGlobal-MT5 5`:
  final controlled round trip BUY `0.1`, modify, SELL close, order/position
  `902855238`, all retcodes `10009`, six correlated events, and positions
  `0 -> 0`; raw log SHA-256
  `8ce133a39633b8b3f8ffed93bddc7c12b83a8d774993c798e85512fe3367e409`.
- the first live attempt correctly failed closed with client retcode `10027`
  while Algo Trading was disabled. Enabling the isolated DEMO clone caused an
  older attached harness to open/close one additional `0.02` DEMO round trip;
  it was removed, all positions were verified closed, then the current `0.1`
  correlated chain was run. No REAL account was touched.
- actual native spools were ingested into a fresh SQLite DB: 12 unique rows,
  nine recipient deliveries for ready/open/close, six diagnostic events
  suppressed from Telegram, zero GOLDM delivery to the GOLDI-approved
  audience, and both offsets fully ACKed.
- the isolated clone was returned to Algo Trading OFF and closed cleanly;
  the main terminal setting was never changed.

- actual dev Telegram Bot API delivery PASS: six final messages, zero failures,
  hashed recipient identity, persisted message IDs, and no raw token/chat ID in
  evidence. The available chat overlapped admin and approved roles; the
  distinct-recipient capture matrix separately proves subscriber isolation.
- exact GOLDM refusal harness PASS for wrong account, wrong server, and DEMO
  mode with magic `26081912`, disabled authority, unchanged tester balance, and
  no mutation.
- final compile: two profile EAs and three harnesses 0 errors/0 warnings.
- full regression PASS: 834 fast and 218 slow tests.
- quality gate PASS: Ruff/mypy, 90.12% safety-core coverage, and 82.66%
  changed-rule coverage.

Final certification:

- strict verifier PASS with native lifecycle, refusal, SQLite correlation, and
  actual Telegram receipt inputs;
- both complete E2E chains and cross-profile routing are proven;
- production REAL authority stayed disabled.

REAL orders: **DISABLED**
