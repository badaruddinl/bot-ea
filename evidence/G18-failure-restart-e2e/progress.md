# G18 Failure and Restart E2E

Status: **IN_PROGRESS**

Locked scope:

- dependency failures: bridge, DB, Telegram, backlog, and recovery while EA
  decision/management remains independent;
- broker/MT5 failures: disconnect, Algo off, identity mismatch, market/spread/
  margin/check/send rejection, ambiguous outcomes, manual intervention,
  duplicate EA, and magic collision;
- restart matrix: watch, EA, terminal, Windows/VM, open position, dual terminal,
  and one-profile-only restart;
- require no duplicate, lost ownership, or cross-profile management;
- production REAL order authority remains **DISABLED**.

Current sub-batch:

- extending deterministic failure injection around the certified G14 execution
  guard, G16 bridge store, and G17 correlated chain;
- separating failures that can be proven in pure/native harnesses from actual
  terminal/process restart evidence.

REAL orders: **DISABLED**
