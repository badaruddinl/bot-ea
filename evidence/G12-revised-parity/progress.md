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
- dual-profile compile: 0 errors, 0 warnings;
- G11 runtime invariants remain intact;
- 10 focused tests passed.

Remaining before PASS:

- setup detector and restart state;
- supply/demand and first obstacle;
- entry/stop/target;
- complete decision reasons and evidence;
- Python/MQL5 event-state-reason parity 100%;
- entry/SL/TP tolerance no greater than one profile tick.

REAL orders: **DISABLED**
