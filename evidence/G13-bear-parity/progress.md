# G13 Bear MQL5 Parity

Status: **PASS**

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
- semantic profile bug fixed in the Python reference adapter: the Bear M15
  setup scanner is now explicitly constructed with the worker profile symbol
  instead of silently defaulting to `GOLD.i#`; GOLDI/GOLDM regression proves
  exact `GOLD.i#`/`GOLDm#` binding without changing strategy parameters;
- focused profile-binding/reference regression: 48 passed.
- profile-cost binding corrected in the same adapter: the M15 scanner now uses
  the exact BearV4 spread floor (`0.20` GOLD.i, `0.24` GOLDm), proven by the
  same dual-profile regression without changing any decision threshold;
- read-only MT5 oracle captured from `GOLDm#` at 18 Aug 2026 17:00 server time,
  normalized per profile floor and frozen as two hashed 50-bar vectors;
- complete standalone M15 confluence-v1 port: regime, swing/psychological
  resistance and support, rejection, Fibonacci, RSI7, Stochastic, supply,
  momentum, exhaustion, structural stop, nearest barrier, continuation, and
  two targets;
- deterministic generator produces the 50-bar MQL5 harness fixture from the
  hashed oracle, preventing hand-edited parity samples;
- native GOLDm chart harness PASS:
  `h1_m5_m1=true incremental=true m15=true`;
- current harness binary SHA-256:
  `c6ecd83f855407cc83bed3ab885b5cf25c9d18ed88df8d3c19088a842500c954`;
- focused oracle/contract suite: 9 passed.
- native GOLDm terminal matrix extended and PASS:
  `h1_reject=true m5_acceptance=true restart_expiry=true`, including restart
  from WATCH_M1 to exact sequence-66 entry, duplicate no-op, old-bar rejection,
  and sequence-85 M1 expiry;
- expanded native harness/fixture suite: 12 passed, compile 0 errors/warnings.
- runtime persistence uses two alternating profile-specific binary slots; each
  carries schema magic, profile fingerprint, symbol, semantic offset, complete
  state/buffers/cursors, and bounded lengths. Load chooses the highest valid
  sequence, rejects corrupt/foreign identity, and treats state older than 180
  seconds as stale seed-only recovery;
- native persistence round-trip PASS: WATCH_M1 slot B -> entry sequence 66 slot
  A -> latest-slot recovery, plus stale and wrong-fingerprint rejection;
- final focused persistence/runtime matrix: 42 passed;
- final warning-clean binaries: GOLDI
  `eb50d61f1b5b8601ee3dba926c448a133368b775998cc7de44c33126ed7aa3e2`,
  GOLDM
  `4e321b578f53d270e7a82631be4b6fc7e2fb05fe5433b6ac51bca6b5838e951f`,
  harness
  `ab321e1987a630797bce578700ee5a357d0fd244cc62a8664f6661e432bde91e`.
- shared runtime now seeds bounded Bear history without promotion, evaluates
  only the newest 50-bar M15 window, feeds each H1/M15/M5/M1 closed bar once,
  exposes the last Bear signal/phase, and emits ENTRY_READY without order API;
- D1 bars are explicitly excluded from the Bear machine and runtime stays
  fail-closed on cursor/data errors;
- dual-profile runtime compile: 0 errors, 0 warnings;
- runtime binary SHA-256: GOLDI
  `b98e8245835b98bbe31d7a42397dfeb6401da75f0cbd47fbb3ac642853651ee9`,
  GOLDM
  `fa6dd2422a8ee6b65335af6b2ed82a319d57aea8351ad4f5bbe9856f3dce4866`;
- focused runtime/Revised/G11 regression: 26 passed.
- GOLDm Strategy Tester capture PASS on `GOLDm#`, M15, server
  `XMGlobal-MT5 14`; full native marker includes H1/M5/M1, incremental M15,
  rejection, acceptance, restart/expiry, and persistence parity;
- compile evidence PASS for both profile binaries and the Bear harness on
  MetaEditor 6090 with 0 errors and 0 warnings;
- full regression PASS: 685 fast tests and 154 slow tests;
- incremental quality gate PASS: Ruff, mypy, 90.12% safety-core coverage,
  82.66% changed-rule coverage, and 238 focused tests;
- legacy G12 corpus sidecars were corrected to the exact already-committed
  bytes and all deterministic vector tests pass; no strategy value changed.

Final certification:

- GOLD.i Strategy Tester PASS on `GOLD.i#` / `XMGlobal-MT5 5` with the same
  complete native marker as GOLDm, `OnTester result 1`, one tick/one bar, and
  unchanged 100.00 USD tester balance;
- final dual-profile evidence verifier PASS:
  `96fdd9c8805e5fb984c70569473a8acaaa19c90ba2d4c3ba6889f137aab408d6`.

REAL orders: **DISABLED**
