# G13 Bear MQL5 Parity

Status: **IN_PROGRESS**

Locked scope:

- port the bounded Python incremental state machine, never the historical
  replay loop;
- preserve `IDLE -> WATCH_H1 -> WATCH_M5 -> WATCH_M1 -> ENTRY_READY` and every
  cancellation path;
- process closed M15/H1/M5/M1 bars once in semantic close-time order;
- preserve exact state, reason, timestamps, touches/rejections, and SELL
  geometry;
- certify restart state, profile isolation, and no historical promotion;
- keep Python reference and production REAL order authority disabled.

Current sub-batch:

- canonical GOLDI/GOLDM Python vectors for happy-path entry, durable WATCH_M1
  restart state, H1 rejection, M5 acceptance cancellation, and M1 expiry.
- standalone MQL5 Bear types and exact ATR/RSI/Stochastic helpers without
  Revised imports, indicator handles, replay, network, or order authority;
- exact H1 bearish context, M5 touch/rejection/acceptance arming, and M1
  micro-break/oscillator/structural geometry functions;
- native profile-sensitive harness locks GOLD.i spread floor 0.20 versus GOLDm
  0.24 and the resulting stop/target geometry;
- MetaEditor 6090 compile: 0 errors, 0 warnings;
- harness binary SHA-256:
  `696d9048e151ad38854e6425524ee3fb24c72ce75d9b409eb8399456e668e6ba`;
- focused corpus/contract suite: 6 passed.

Remaining before PASS:

- M15 confluence setup scanner port;
- bounded incremental state owner, closed-bar cursors, transitions, events,
  terminal reset, and restart snapshot/restore;
- runtime integration and explicit proof that live code cannot full-replay;
- all cancellation/restart vectors in the native harness;
- dual-profile Strategy Tester, compile, regression, and final verifier.

REAL orders: **DISABLED**
