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
- dependency lab PASS on the actual G17 spools: DB unavailable fails closed,
  12-event bridge backlog recovers, nine Telegram failures persist retry state,
  recovery drains all nine, replay reports 12 duplicates without adding rows,
  and source spools remain byte-identical.
- new Common Files exclusive lease rejects a second profile/account/magic EA
  instance across chart or terminal process. Native harness PASS: first owner,
  duplicate refusal, release, then recovery acquisition; no trade mutation.
- lease namespace test also holds GOLDM alive while GOLDI is released and
  reacquired, proving one-profile restart does not evict or overwrite the other
  profile's lock.
- broker ambiguous-result handling now performs no blind retry. Only timeout,
  connection, or generic ambiguous retcodes enter exact symbol+magic+signal
  comment reconciliation, and exactly one matching position is required.
  Partial success and hard funds/invalid rejects are classified explicitly.
- captured expected broker failures: market closed `10018`, Algo Trading off
  `10027`, positions unchanged, plus existing guard coverage for wrong identity,
  extreme spread, margin, broker check, geometry, and duplicate signal.
- actual GOLDI DEMO open-position process restart PASS: ticket `902911581` was
  opened at `0.01`, terminal stopped with the position alive, the next process
  synchronized with one position, loaded the profile-bound slot, closed the
  same ticket with retcode `10009`, cleared state, and ended at zero positions.
- restart testing exposed a delimiter bug when signal IDs contained `|`.
  Persistence now parses fixed numeric fields from the record tail and safely
  reconstructs delimiter-containing signal IDs; native round-trip/corruption/
  fallback/manual-change harness remains PASS.

Remaining matrix:

- explicit disconnect/reconnect transition capture;
- manual close and magic-collision aggregation into G18 certification;
- actual dual-terminal/process concurrency beyond the Common Files lease proof;
- final compile/regression/resource-independent G18 sealing.

REAL orders: **DISABLED**
