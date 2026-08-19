# GOLDM dual TP1/TP2 research

## Scope

- Total lot 0.02, represented by two 0.01 legs for split policies
- Starting cash view: USD 100
- REVISED BUY TP1: original structural engine target
- REVISED BUY TP2: 2.5× scaled target
- Bear SELL TP1: whichever of structural support target and exact 2R is closer
- Bear SELL TP2: the farther of those two targets
- Closed M1 causal replay; same-bar stop/target is conservative

Policies:

- `FULL_TP2`: retain the full 0.02 lot to TP2;
- `FULL_TP1`: close the full 0.02 lot at TP1;
- `SPLIT_KEEP_STOP`: close 0.01 at TP1 and keep the original stop for the
  remaining 0.01;
- `SPLIT_BE_AFTER_TP1`: close 0.01 at TP1 and move the runner stop to entry
  beginning with the next M1 bar.

The mandatory three partial windows were run first. FULL TP2 was best in all
three for both engines, so no August tweaking was required and full suite was
run last.

## REVISED BUY

### Partial R result

| Window | Full TP2 | Full TP1 | Split keep stop | Split BE |
|---|---:|---:|---:|---:|
| Jan 2025–now | **+121.30R** | +76.03R | +98.66R | +96.65R |
| Nov–Feb | **+33.47R** | +9.23R | +21.35R | +17.60R |
| Jun–now | **+13.99R** | +5.74R | +9.87R | +10.35R |

### Full suite

| Policy | Signals | TP1 reached | TP2 reached | Total R | Expectancy | R DD | Ending balance | PF | Cash DD |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full TP2 | 959 | 512 | 319 | **+180.94R** | **+0.189R** | 29.50R | **$2,017.66** | 1.40 | 59.58% |
| Full TP1 | 959 | 512 | 22* | +117.93R | +0.123R | 21.43R | $1,179.42 | 1.33 | **33.72%** |
| Split keep stop | 959 | 512 | 319 | +149.43R | +0.156R | 16.60R | $1,599.49 | **1.45** | 39.00% |
| Split BE after TP1 | 959 | 512 | 234 | +144.27R | +0.150R | **15.60R** | $1,423.44 | 1.40 | 33.19% |

`*` TP2 is an observation after a full TP1 close and does not affect its P/L.

For REVISED, split keep-stop is a valid capital-protection profile: it cuts R
drawdown by about 44% and raises PF slightly. It also sacrifices about 22% of
fixed-lot net profit. FULL TP2 remains the primary performance policy.

## Bear SELL v4 exact-2R candidate

### Partial R result

| Window | Full TP2 | Full TP1 | Split keep stop | Split BE |
|---|---:|---:|---:|---:|
| Jan 2025–now | **+29.57R** | +7.44R | +18.50R | +21.00R |
| Nov–Feb | **+8.67R** | +0.90R | +4.78R | +4.78R |
| Jun–now | **+6.00R** | +0.58R | +3.29R | +2.79R |

### Full suite

| Policy | Signals | TP1 reached | TP2 reached | Total R | Expectancy | R DD | Ending balance | PF | Cash DD | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Full TP2 | 306 | 147 | 121 | **+94.80R** | **+0.310R** | **9.15R** | **$662.38** | **1.36** | **27.93%** | completed |
| Full TP1 | 307 | 148 | 58* | +23.90R | +0.078R | 12.64R | $1.63 | 0.94 | 88.80% | **stop-out** |
| Split keep stop | 306 | 147 | 121 | +58.35R | +0.191R | 10.39R | $378.00 | 1.21 | 36.31% | completed |
| Split BE after TP1 | 306 | 147 | 109 | +59.04R | +0.193R | 10.47R | $398.33 | 1.23 | 40.33% | completed |

For bear, TP1-only and split policies are inferior in both return and full-suite
drawdown. FULL TP2 remains the only selected policy.

## Initial split-policy decision

- REVISED primary: FULL TP2, no split.
- REVISED optional protection research profile: 50/50 split with original
  runner stop, not enabled.
- Bear primary: FULL TP2, no split.
- Bear TP1-only and split variants are rejected.
- No runtime, worker, or order behavior is changed by this research.

## Engine-decided BEP milestone research

TP1 is reinterpreted as a milestone, not a mandatory partial close. The entire
0.02 lot remains assigned to TP2. When TP1 is reached, the engine may move the
whole-position stop to BEP beginning on the next M1 bar.

The decision is made from entry-time evidence:

- REVISED moves BEP only for RANGE setups with first-obstacle room at least 1R
  and TP2 at least twice as far as TP1. MOMENTUM setups retain their structural
  stop so an ordinary retracement does not remove the runner.
- Bear moves BEP only when M1 has at least two touches, TP2 crosses structural
  support, and TP2 is at least 1.5 times TP1 distance.

No result/future field participates in the decision.

### 4–19 August tuning evidence

| Engine | Full TP2 | Universal BEP | Engine-decided BEP |
|---|---:|---:|---:|
| REVISED | +11.95R | +10.91R | **+12.95R** |
| Bear | +3.00R | +1.00R | **+3.00R** |

REVISED engine-BEP saves one RANGE stop without removing the MOMENTUM runner
that universal BEP incorrectly closes. Bear engine-BEP avoids the universal
BEP false close and leaves the valid August outcomes unchanged.

### Frozen-rule partial revalidation

| Engine/window | Full TP2 R | Engine-BEP R | Full TP2 cash | Engine-BEP cash |
|---|---:|---:|---:|---:|
| REVISED Jan | +121.30R | **+127.96R** | $1,444.46 | **$1,505.75** |
| REVISED Nov–Feb | **+33.47R** | +30.63R | $486.18 | **$489.08** |
| REVISED Jun | +13.99R | **+15.99R** | $197.17 | **$219.19** |
| Bear Jan | +29.57R | +29.57R | unchanged | unchanged |
| Bear Nov–Feb | +8.67R | +8.67R | unchanged | unchanged |
| Bear Jun | +6.00R | +6.00R | unchanged | unchanged |

REVISED November R declines slightly, but fixed-lot ending balance and PF
improve in all three partial windows. January cash drawdown worsens, so this is
not a free risk reduction.

### Full suite

| Engine | Policy | Total R | Expectancy | R DD | Ending balance | PF | Cash DD |
|---|---|---:|---:|---:|---:|---:|---:|
| REVISED | Full TP2 | +180.94R | +0.189R | 29.50R | $2,017.66 | 1.40 | 59.58% |
| REVISED | **Engine-BEP** | **+209.48R** | **+0.218R** | **25.18R** | **$2,126.15** | **1.51** | **47.73%** |
| Bear | Full TP2 | +94.80R | +0.310R | 9.15R | $662.38 | 1.36 | 27.93% |
| Bear | **Engine-BEP** | **+95.80R** | **+0.313R** | **9.15R** | **$673.22** | **1.37** | **27.93%** |

Engine-decided BEP is the first TP1/TP2 mechanism to improve full-suite R,
expectancy, cash profit, and PF for both engines without partial close. It is
retained as a research candidate only; runtime remains unchanged pending an
explicit application instruction and execution-cost stress.
