# G19 Resource, Storage, and Latency Stability

Status: **IN_PROGRESS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remains **DISABLED**.

Current batch:

- capture GOLDI and GOLDM terminal working set, private bytes, CPU, handle/thread
  counts, and heartbeat progress as separate time series;
- capture bridge memory/CPU plus DB/WAL and profile spool sizes;
- prove idle operation does not create per-tick DB or spool growth;
- add acknowledged-spool compaction/rotation that cannot discard events pending
  in the durable bridge database;
- derive resource trends from the observed baseline rather than inventing fixed
  RAM limits;
- record the six required latency stages from causal timestamps and actual E2E
  receipts where available;
- prove one profile remains responsive while the other is loaded.

The VM scheduled-task launchers used for G18 are temporary interactive-logon
probes. Unattended `At startup` operation without desktop login is a locked G20
acceptance condition and is not claimed by G19.

REAL orders: **DISABLED**
