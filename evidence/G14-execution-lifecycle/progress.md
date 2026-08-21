# G14 EA Execution and Position Lifecycle

Status: **IN_PROGRESS**

Locked scope:

- port the certified Python execution contract before adding broker mutation;
- preserve structural SL/TP and reject quote chasing;
- bind every request and discovered position to exact profile, account, server,
  trade mode, symbol, magic, and signal identity;
- handle retcode, filling, stops/freeze, margin, modify/close, manual
  intervention, and restart recovery;
- keep Python production order authority off before any MQL5 tester authority
  is enabled;
- keep production REAL order authority **DISABLED**.

Current sub-batch:

- native immutable plan/context/order contracts now carry profile/version/hash,
  account/server/mode/terminal, symbol/magic, validity, volume/tick, policy,
  structural prices, invalidation, and planned risk;
- pure execution guard implements all 18 Python reference reject reasons,
  deterministic primary reason, BUY/SELL executable quote selection, and
  structural SL/TP preservation without order mutation;
- GOLDI and GOLDM profile policy locks match Python: tick `0.01`, drift `0.15R`,
  spread `0.60`/`0.72`, and age 60 seconds;
- focused Python/static regression: 24 passed;
- MetaEditor 6090 compile: GOLDI, GOLDM, and guard harness all 0 errors and 0
  warnings;
- native GOLD.i Strategy Tester guard matrix PASS with GOLDI/GOLDM true,
  all 18 reason classes, structural geometry true, `OnTester result 1`, final
  tester balance 100.00 USD, and order authority disabled;
- native guard log SHA-256:
  `d01e11ce0d8e243a8a5d10f152b301c5794217c6a802216f08f83a9eab2afd82`;
- current binary SHA-256: GOLDI
  `61094b8015a2ce0c37d5c117991e33a08d4bdb2148a77c872a46b095f3b84b12`,
  GOLDM `31dd9d5a35dd11965f88f196f2617a7d2ad610b1dca80ee6c48a5b1fbca6594d`,
  guard harness
  `1199ce84a7ab7ca6cc94f0ad8afbb427b6909e897a7d34773a28ebb50d7cf82c`.
- read-only broker collector now obtains account/server/mode/free margin, symbol
  tick/point/volume/stops/freeze/order capabilities, profile-owned exposure,
  duplicate comment identity, calculated margin, deterministic filling mode,
  immutable `MqlTradeRequest`, and `OrderCheck` result;
- actual GOLD.i Strategy Tester broker preflight PASS: collected/validated/
  order-check true, retcode `0`, `ORDER_FILLING_IOC`, margin 8.75 USD, zero
  owned positions, unchanged structural SL/TP, `OnTester result 1`, and no
  mutation authority;
- broker preflight log SHA-256:
  `78bec146371ba61d334bda424b022653cbd99cb87ca75e04f29865f0c5a35a57`;
- broker harness binary SHA-256:
  `ae224c04b743cc22a1748b01e4d1601467331a51cdcc735d4b601455cfe5c7a2`;
- focused broker/guard/capture regression: 11 passed; broker harness compile
  0 errors and 0 warnings.
- `CExecutionBroker` now configures synchronous `CTrade`, exact profile magic,
  deviation, symbol filling, explicit success retcodes, full result receipt,
  and routes every request through broker collection plus pure validation;
- the mutation call is structurally below `m_authority_enabled`; unsafe profile
  defaults fail initialization and authority remains false unless explicitly
  requested;
- native disabled-authority Strategy Tester PASS: initialized true,
  validation true, submitted false, positions `0 -> 0`, receipt disabled,
  `OnTester result 1`, final balance 100.00 USD;
- disabled-authority log SHA-256:
  `7ecddc4667e08f589a073203a2480f85408cedab13a5d703566481813c5658a3`;
- disabled-authority harness binary SHA-256:
  `635ab0672704beb9be754f8ae1b53201e424b4ebaeedfa827d9c3fda93245423`;
- focused CTrade interlock/capture regression: 8 passed; harness compile 0
  errors and 0 warnings.
- position lifecycle is ticket-scoped and refuses wrong symbol, magic, or
  profile comment before modify/close; discovery distinguishes foreign-symbol
  positions and comment-level manual intervention;
- initial lifecycle probe correctly exposed a harness timing bug: order at
  00:00 server was rejected as market closed (`10018`). The harness now waits
  for a closed-market-safe execution time (first tick at/after 02:00 server)
  and has an `OnDeinit` cleanup path;
- fixed Strategy Tester lifecycle PASS: open, ownership discovery, SL modify,
  reconstructed broker object, restart rediscovery, and close all true;
  positions `0 -> 0`, open/modify/close retcodes all `10009`, magic
  `26081911`, `OnTester result 1`;
- lifecycle log SHA-256:
  `969db269a0d8f1f6b363758a83da3198735d50f3dac143e1f9a9c884bbe4744e`;
- lifecycle harness binary SHA-256:
  `e35c001d6f7865a6180830a0efedc8f0202cf1ec98ed4f368dcb13ba7e4f1564`;
- lifecycle tester balance ended at 99.62 USD solely from simulated spread on
  the immediate open/close round trip; no external account was touched;
- focused lifecycle/capture regression: 11 passed; compile 0 errors and 0
  warnings.
- shared runtime now converts final non-observation Revised and Bear decisions
  into full immutable plans, applies adaptive profile lot sizing, calls the
  guarded broker once per final signal, and records sent/disabled/rejected
  transition outcomes;
- both thin profile entrypoints expose `InpEnableOrderAuthority=false` and
  forward trade transactions; startup and every relevant transaction
  rediscover owned positions and disable authority on foreign-symbol magic or
  profile-comment intervention;
- main profile binaries compile warning-clean with execution runtime:
  GOLDI `fe8771d2fa79650e9ef35abdc78ff71674749b95e50f3e5d8c73f5e047533826`,
  GOLDM `be5920069b719728c9faaaa91e049f8d5ff13f5b67df7256b1ae9f808210df92`;
- focused runtime/Revised/Bear/G11 regression: 35 passed.

Next sub-batch:

- `CTrade` request/retcode/filling execution behind disabled-by-default
  authority;
- owned-position discovery, modify/close, manual intervention, and restart
  recovery.

REAL orders: **DISABLED**
