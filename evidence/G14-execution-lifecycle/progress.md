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

Next sub-batch:

- broker context collector and preflight `OrderCheck`;
- `CTrade` request/retcode/filling execution behind disabled-by-default
  authority;
- owned-position discovery, modify/close, manual intervention, and restart
  recovery.

REAL orders: **DISABLED**
