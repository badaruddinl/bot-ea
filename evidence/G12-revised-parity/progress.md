# G12 Revised MQL5 Parity

Status: **IN_PROGRESS**

Completed sub-batch:

- exact scalar Revised config defaults;
- explicit snapshot/decision optional geometry;
- ATR, Wilder RSI, swing high/low, and tick normalization primitives;
- repeated-touch range, rejection, acceptance, and excursion statistics;
- M1 vote, micro-break, close-location, strong and latched confirmation;
- momentum displacement/expansion and exhaustion signals;
- Fibonacci impulse/retest/current-rejection statistics;
- hard invalidation acceptance;
- adaptive M1 structural stop selection, fallback risk, target buffering, and
  snapshot causal validation;
- confirmed M5/H1 supply-demand zones, acceptance, market regime, psychological
  levels, swing candidates, and M1 pre-trigger obstacle clusters;
- M5 setup classification, reinforcement, opposite cancellation, expiry,
  consume semantics, and restart-state snapshot/restore;
- complete Revised 0.6.0 decision tree, reasons, confidence caps,
  observation-only/scalper behavior, and entry-ready geometry;
- runtime-owned bounded history, warm-up seeding, BUY/SELL evaluation,
  termination, consume, and entry-ready transition;
- deterministic native parity harness for the Python range-entry vector;
- canonical hashed Python corpus with ten GOLDI/GOLDM vectors covering
  no-setup, BUY/SELL range entry, sub-1R obstacle watch, and momentum entry;
- canonical hashed setup-state corpus with twelve GOLDI/GOLDM vectors covering
  M5 acceptance, reinforcement, restart restore, consumed no-resurrection,
  expiry termination, and opposite-setup cancellation;
- native harness assertions for exact setup fields, semantic trigger times,
  preserved maximum watch age, reinforcement trigger identity, restart
  restoration, one-shot termination delivery, and consumed-state recovery;
- typed nested range/M1/momentum/risk/Fibonacci decision evidence;
- dual-profile compile: 0 errors, 0 warnings;
- expanded dual-profile and harness compile: 0 errors, 0 warnings on
  MetaEditor build 6090;
- final G12 verifier checks both hashed corpora, profile fingerprints, clean
  compile evidence, both full native state/restart markers, symbol isolation,
  and disabled REAL authority; it currently fails closed because the GOLD.i
  native capture does not yet exist;
- native GOLDm decision-only harness PASS was captured before the setup-state
  expansion; it is retained only as preliminary evidence and cannot satisfy
  final G12 acceptance;
- expanded native GOLD.i PASS on `GOLD.i#`, `XMGlobal-MT5 5`, account DEMO:
  all ten decision/setup/restart assertions true, one tick, one bar, OnTester
  result 1, and unchanged 100.00 USD tester balance;
- GOLD.i raw final evidence is stored externally under
  `E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G12-revised-parity\final`;
- 663 fast tests passed with 77 subtests;
- 154 slow tests passed with 64 subtests;
- G11 runtime invariants remain intact;
- 34 focused MQL5/restart/compile-evidence tests passed.

Remaining before PASS:

- rerun the expanded native harness on GOLDm and capture the full state/restart
  marker;
- run and capture the expanded native harness on GOLDm after the user-owned
  REAL account login dialog is completed (tester-only; no order authority);
- finalize per-profile event/state/reason/timestamp and geometry reports.

REAL orders: **DISABLED**
