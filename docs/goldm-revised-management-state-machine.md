# GOLDM_REVISED — post-entry management state-machine research

## Scope

- Research-only; REVISED runtime and production are unchanged
- Candidate entry/SL/TP: stop multiplier 1.75, target multiplier 2.5
- Management uses only completed M1 bars
- Initial tests follow the mandatory three-partial-first workflow

## State model

```text
INITIAL → PROFIT → OBSTACLE → NEAR_TARGET
                    ↓
          INVALIDATION_PENDING → MANAGED_EXIT
```

Observed evidence combines achieved R, first-obstacle touch, 80% target
proximity, bars since peak, bearish micro-break, three-bar momentum reversal,
two-close acceptance below entry, and optional two-M5-close persistence.

Policies tested:

- `CONSERVATIVE`: persistent micro-break + momentum + acceptance after 1R,
  obstacle, or near-target state;
- `OBSTACLE_AWARE`: permits a faster near-target momentum exit;
- `M5_PERSISTENT`: also requires two completed M5-equivalent closes below
  entry for ordinary runner invalidation;
- `TYPED_STATE`: separate 0.5–1R fast-fade invalidation from 1R+ runner
  management.

## Initial three partial windows

| Window | Policy | Total R | Expectancy | R DD | Managed exits |
|---|---|---:|---:|---:|---:|
| Jan 2025–now | No management | **+121.30R** | **+0.426R** | **9.62R** | 0 |
| Jan 2025–now | Conservative | +111.05R | +0.382R | 12.06R | 48 |
| Jan 2025–now | M5 persistent | +116.65R | +0.402R | 12.27R | 36 |
| Jan 2025–now | Obstacle aware | +115.19R | +0.376R | 12.06R | 91 |
| Nov–Feb | No management | **+33.47R** | **+0.531R** | 8.62R | 0 |
| Nov–Feb | Conservative | +27.84R | +0.435R | **8.45R** | 6 |
| Nov–Feb | M5 persistent | +27.92R | +0.436R | **8.45R** | 6 |
| Nov–Feb | Obstacle aware | +25.18R | +0.376R | 9.16R | 16 |
| Jun–now | No management | +13.99R | +0.777R | 3.00R | 0 |
| Jun–now | Conservative | **+14.54R** | **+0.808R** | 3.00R | 1 |
| Jun–now | M5 persistent | +14.49R | +0.805R | 3.00R | 1 |
| Jun–now | Obstacle aware | +12.92R | +0.718R | 3.00R | 2 |

No policy improves all three windows. Management reduces return materially in
January and November for only a small June improvement.

## 4–19 August tweaking evidence

The five August STOPs include three prior profitable paths:

- +0.93R medium fade: reversal evidence completes within four minutes, on or
  too near the hard-stop bar;
- +0.28R shallow fade: reversal and stop occur only two minutes after peak;
- +0.85R medium fade: micro/momentum appear after one minute, but two-close
  acceptance appears at minute 13 and stop at minute 14.

The first typed-state attempt allowed 0.25–1R fast-fade management. It closed an
eventual winner at -0.55R after that winner had reached only +0.30R, reducing
August total from +11.95R to +9.42R. Raising the fast-fade floor to 0.50R avoids
the false close but produces no managed exits and exactly matches no-management.

## Decision

No state-machine candidate is better than no-management. Closed-bar evidence is
too late for the fastest failures, while earlier evidence also occurs during
normal retracement in eventual winners. Per the mandatory workflow, the
experiment stops at the August tweaking stage: it does not return to partial
re-validation and does not run a full suite.

Keep REVISED no-management. The state-machine code remains an isolated replay
tool for future research and is not enabled in shadow/runtime.
