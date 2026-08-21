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

REAL orders: **DISABLED**
