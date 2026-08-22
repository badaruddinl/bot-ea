# G10 Reference Market-Data and Execution Validation

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remains **DISABLED**.

## Actual broker probes

The final VM capture used two distinct MT5 installations and bindings from the
already-installed G20 configuration. No account identifier was hard-coded into
the capture command.

- prerequisites: `ready=true`, no errors, Python 3.14.7, MT5 module available;
- GOLDI: DEMO, `GOLD.i#`, terminal build 6140, M1/M5/M15/H1 closed bars, tick
  captured, latency 8.160 ms, `orders_sent=0`, `order_api_calls=0`;
- GOLDM: REAL read-only, `GOLDm#`, terminal build 6109, M1/M5/M15/H1 closed
  bars, tick captured, latency 9.871 ms, `orders_sent=0`, `order_api_calls=0`;
- account-login and terminal-path values are represented only by SHA-256;
- terminal-path hashes are distinct.

## Execution and concurrency reconciliation

- GOLDI guarded DEMO lifecycle is backed by G15 native lifecycle, the actual
  G17 entry/open/modify/close chain, G18 open-position restart recovery, and
  actual G19 latency receipts;
- GOLDM execution remains Strategy Tester only. G15 proves 100% event/state/
  reason parity and zero price error; G19 supplies the actual 3,916,275-tick
  real-tick window; G18 supplies restart recovery;
- simultaneous GOLDI/GOLDM operation is backed by the 602.013-second G19
  resource capture, G17 profile-isolated bridge routing, G18 dual-terminal
  restart, and G20 fresh-VM acceptance;
- duplicate, state-bleed, privacy-bleed, and live-replay counts are zero.

Each reconciled artifact carries explicit `lineage` references. The source G15,
G17, G18, G19, and G20 evidence remains immutable and independently hashed.

## Acceptance

```text
accepted=true
evidence_fingerprint=deefea781e4edc1b04cd43a7629daa72228940a322766e75f170cdf666f3455d
acceptance_sha256=fd6ff6feb6e79626442c634ad41723e9c47e86e438b985b453925446347be880
production_real_orders=DISABLED
reasons=[]
focused_tests=7 passed
fast_regression=832 passed, 154 deselected, 77 subtests passed
```

REAL orders: **DISABLED**
