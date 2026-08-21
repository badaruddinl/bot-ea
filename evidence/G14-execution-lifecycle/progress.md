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

- expand native immutable plan/context/order validation contracts;
- implement pure fail-closed execution guards with exact reject reasons;
- certify guard parity before introducing `CTrade`.

REAL orders: **DISABLED**
