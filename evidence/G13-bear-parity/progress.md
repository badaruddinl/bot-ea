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
  `3a44530399dfa51d7f5678c9fcf1279de7f730203e4c68daa15fe449173a6e30`;
- bounded MQL5 state owner with per-timeframe closed-bar cursors, duplicate
  idempotence, old-bar rejection, terminal reset-on-next-bar, exact transition
  event IDs, causal `as_of`, and profile-scoped setup identity;
- complete WATCH state snapshot/restore including bounded H1/M15/M5/M1
  buffers, arm evidence, signal, cursors, semantic offset, and no-resurrection
  last-setup time;
- native harness now asserts exact Python happy-path sequence numbers 53/64/66,
  event reasons/timestamps/setup ID, final sequence 68, and terminal IDLE;
- focused corpus/contract suite: 7 passed.

Remaining before PASS:

- M15 confluence setup scanner port;
- runtime integration and explicit proof that live code cannot full-replay;
- all cancellation/restart vectors in the native harness;
- dual-profile Strategy Tester, compile, regression, and final verifier.

REAL orders: **DISABLED**
