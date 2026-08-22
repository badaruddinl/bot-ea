# G19 Resource, Storage, and Latency Stability

Status: **PASS**

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

Completed sub-batch:

- bridge spool compaction resets the producer offset before atomic rotation, so
  a crash can cause duplicate replay but cannot skip a new spool;
- the rotated file is replayed before deletion, capturing append-at-rotation
  races while all pending deliveries remain durable in SQLite;
- orphaned rotation files are replayed and cleaned after bridge/VM restart;
- a busy Windows producer handle fails compaction closed and restores the exact
  acknowledged offset for retry;
- bridge suite: 24 passed; Ruff and mypy PASS.
- strict stability analyzer now derives post-warm-up window trends from observed
  noise instead of a fabricated RAM ceiling, fails on profile starvation or
  idle storage growth, and requires all six latency stages;
- Windows collector samples exact GOLDI/GOLDM executable paths plus the bridge,
  heartbeats, DB/WAL, and both spools; it contains no order, restart, or network
  action;
- analyzer/collector focused tests: 7 passed; quality gate PASS with core
  90.12% and strategy rules 82.66%.
- first 10-minute capture correctly failed: the bridge rewrote its offset every
  idle poll (95 WAL growth observations) and exposed the write-idle defect;
- after the fix, the repeated 120-sample/599.48-second capture passed resource
  and storage checks: no ongoing monotonic leak, both heartbeats advanced 599
  generations, and DB/WAL/GOLDI-spool/GOLDm-spool each had zero idle growth;
- the repeated capture's latency input is explicitly preliminary. G19 remains
  IN_PROGRESS until all six stages are replaced by actual causal/native/E2E
  measurements.
- final-engine baseline repeated with profile-locked `GoldEngine-GOLDi` and
  `GoldEngine-GOLDm` binaries, explicit expected login/server inputs, and order
  authority disabled: 120 samples/602.01 seconds PASS, zero idle DB/WAL/spool
  growth, no ongoing leak, and both process liveness counters advanced;
- actual bridge pipeline measured 100 iterations for enqueue-to-SQLite and
  enqueue-to-capture-sender. This is labeled internal/no-network and is not
  misrepresented as Internet Telegram latency;
- native runtime now records the first four latency stages on the existing
  `POSITION_OPENED` transition without adding tick-path I/O or a new per-tick
  event; both final profile binaries compile with 0 errors and 0 warnings.
- the scheduler now validates exact broker-bar topology instead of wall-clock
  continuity, so overnight/weekend session gaps remain valid while genuinely
  skipped broker bars still fail closed;
- actual Strategy Tester runs processed 3,958,514 GOLD.i ticks and 3,916,275
  GOLDm ticks without `CLOSED_BAR_GAP`; 14 GOLDI and 10 GOLDM opened-position
  receipts supplied 24 native latency samples in total;
- the GOLDm tester-only mode override is derived solely from `MQL_TESTER` and
  cannot be enabled by an EA input or persisted state in a live terminal;
- strict assembled analysis PASS: 120 resource samples over 602.01 seconds,
  zero idle DB/WAL/profile-spool growth, no monotonic leak, and all six latency
  stages measured from actual native/bridge receipts;
- latency p95: bar-close-to-detection 185.60 ms, detection-to-decision 42.25 ms,
  entry-ready-to-submit 1.02 ms, tester submit-to-broker-ack 0.211 ms,
  enqueue-to-DB 41.83 ms, enqueue-to-capture-sender 46.13 ms. The final sender
  metric is explicitly internal and does not claim Internet Telegram latency;
- final regression: 796 fast tests plus 77 subtests PASS; 154 slow tests plus
  64 subtests PASS; quality gate PASS at core 90.12% and rules 82.66%.

The VM scheduled-task launchers used for G18 are temporary interactive-logon
probes. Unattended `At startup` operation without desktop login is a locked G20
acceptance condition and is not claimed by G19.

REAL orders: **DISABLED**
