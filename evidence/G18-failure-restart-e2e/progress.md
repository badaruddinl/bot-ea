# G18 Failure and Restart E2E

Status: **PASS**

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
- actual dual-terminal process probe PASS: GOLDI DEMO and GOLDm REAL-read-only
  terminals ran concurrently with exact account/server/fingerprint heartbeats;
  GOLDI restarted while GOLDm generation advanced with stable identity, then
  both terminals restarted and produced new identities. Both probes contain no
  order API and reported authority DISABLED.
- strict two-phase Windows reboot probe is prepared. `Prepare` locks the actual
  OS boot ID and both profile heartbeats; `Complete` requires a changed boot ID,
  post-boot heartbeat timestamps, unchanged fingerprint/account/server, and
  changed process identities. It contains no reboot command and correctly
  rejects completion on the current unchanged boot.
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

Final certification:

- actual Windows Server VM reboot PASS with changed boot ID;
- both profile fingerprints, accounts, and servers remained exact;
- both profile runtime identities changed and heartbeats were written after the
  new boot;
- strict `verify_g18_evidence.py` certification PASS with no duplicate, lost
  ownership, or cross-profile management;
- fast regression: 776 passed, 154 deselected, 77 subtests;
- slow regression: 154 passed, 776 deselected, 64 subtests;
- incremental quality gate PASS: core 90.12%, strategy rules 82.66%;
- VM process probe compile: GOLDI/GOLDM each 0 errors and 0 warnings.

REAL orders: **DISABLED**
