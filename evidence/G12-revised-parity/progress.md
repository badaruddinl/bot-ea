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
- dual-profile compile: 0 errors, 0 warnings;
- G11 runtime invariants remain intact;
- 10 focused tests passed.

Remaining before PASS:

- supply/demand-aware entry decision and complete target selection;
- complete decision reasons and evidence;
- Python/MQL5 event-state-reason parity 100%;
- entry/SL/TP tolerance no greater than one profile tick.

REAL orders: **DISABLED**
