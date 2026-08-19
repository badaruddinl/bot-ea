# Current production versus research candidates — August 2026

## Scope

- Common broker window: `[2026-08-04 00:00, 2026-08-19 00:00)`, GMT+3
- Symbol: `GOLD.i#`
- Current production baseline: `GOLDM_SNIPER_PARITY`, source baseline
  `4789a10b8b665f5611809edbed3e4ef66a0da557`
- BUY candidate: `GOLDM_REVISED`, stop multiplier 1.75 and target multiplier 2.5
- SELL candidates: `goldm_bear confluence-v4`, normal structural stop
- All results are diagnostic/in-sample; no candidate is deployed

The production number comes from the exact compiled MQL5 Strategy Tester. The
candidate numbers come from causal Python broker-bar replay. They share the
same time window and R unit but are not the same implementation/runtime.

## R comparison

| Engine | Side | Signals | TP / SL | Total R | Expectancy | Max DD | Structural audit |
|---|---|---:|---:|---:|---:|---:|---|
| Current production exact | 20 BUY / 2 SELL | 22 | P(hit 1R) 45.45% | **-2.48R** | **-0.113R** | not exported | 17 M1 fallback attempts |
| REVISED 1.75× : 2.5× | BUY | 11 | 6 / 5 | **+11.95R** | **+1.086R** | 1.00R | 11/11 targets beyond first obstacle |
| Bear v4 fixed 2.0R | SELL | 3 | 2 / 1 | **+3.00R** | **+1.000R** | 1.00R | 3/3 targets beyond structural support |
| Bear v4 0.35R structural cap | SELL | 3 | 3 / 0 | **+1.05R** | **+0.350R** | **0.00R** | 0 targets beyond support |

## Interpretation

Current production is the only negative engine in the exposed August window.
Its exact tester emitted twice as many signals as REVISED and relied heavily on
M1 fallback. This supports shadow comparison, but it does not authorize an
automatic production replacement because the research candidates were tuned
using the same exposed interval.

The aggressive BUY and SELL candidates have higher historical R but achieve it
by extending every tested target through the nearest obstacle/support. Bear
0.35R is the only candidate in this comparison that is both positive and fully
structural.

An exact-production full-suite/three-window comparison is not yet available.
Running it requires temporarily closing the currently open local MT5 terminal
so the Strategy Tester can launch; the production VM itself does not need to be
restarted or changed.

## Decision

- Production remains unchanged.
- REVISED 1.75× : 2.5× remains research-frozen.
- Bear v4 2.0R remains the aggressive research candidate.
- Bear v4 0.35R structural cap remains the normal/safe research candidate.
- No runtime, Telegram sender, or order execution is enabled for either
  research engine.
