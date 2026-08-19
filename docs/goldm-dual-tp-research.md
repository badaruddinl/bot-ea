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

## Engine-decided partial close correction

The partial-close interpretation is now explicit:

- the TP1 **price** is the engine's structural target and is not 50% of the
  distance to TP2;
- with total volume 0.02 and broker volume step 0.01, an executed partial must
  close 0.01 and leave a 0.01 runner;
- after the partial is filled, the runner stop moves to entry beginning with
  the next M1 bar;
- setups not selected for a partial retain the full 0.02 runner to TP2.

`ENGINE_PARTIAL_BE` records the allocation mode and whether a partial was
actually filled. The first broad entry-evidence allocation failed the three
mandatory partial windows. August tuning then narrowed the REVISED condition
to RANGE setups whose structural TP1 is 0.75–1.00R and whose TP2/TP1 distance
ratio is at least 2. No August Bear trade justified a partial, so the frozen
Bear rule leaves the full runner intact.

### August tuning and frozen-rule revalidation

| Engine/window | Full TP2 | Engine partial + BE | R DD full/partial | Partial fills |
|---|---:|---:|---:|---:|
| REVISED Aug 4–19 | +11.95R | **+12.04R** | 1.00 / 1.00 | 3 |
| REVISED Jan 2025–now | **+121.30R** | +110.05R | 9.62 / 12.10 | 46 |
| REVISED Nov–Feb | **+33.47R** | +27.65R | 8.62 / 11.10 | 10 |
| REVISED Jun–now | +13.99R | **+14.09R** | 3.00 / 3.00 | 3 |
| Bear Jan 2025–now | +29.57R | +29.57R | 8.00 / 8.00 | 0 |
| Bear Nov–Feb | +8.67R | +8.67R | 3.00 / 3.00 | 0 |
| Bear Jun–now | +6.00R | +6.00R | 4.00 / 4.00 | 0 |

The REVISED partial rule improves the August tuning sample and the June
window, but materially degrades January and November and worsens drawdown.
It therefore **fails the partial-window gate**. No full-suite replay is run,
and neither engine/runtime/order behavior is changed. Bear keeps TP1 as an
analytical milestone but does not pretend a validated partial condition exists.

## Sub-BEP basket profit-lock shadow

This variant implements a less aggressive alternative to moving the runner
directly to break-even. After a 0.01 partial closes at structural TP1, the
remaining 0.01 stop is moved from the original SL to a sub-BEP level that
keeps part of the realized TP1 profit positive at basket level.

The initial transparent rule retains 25% of realized TP1 profit:

```text
realized_tp1_R = tp1_fraction * tp1_R
basket_floor_R = 25% * realized_tp1_R
runner_stop_R = (basket_floor_R - realized_tp1_R) / runner_fraction
```

For a 0.01/0.01 split and TP1 at 0.8R, this produces runner SL at -0.6R
and locks +0.1R for the combined trade. The calculated stop is clamped at the
original -1R and begins on the next M1 bar. BUY and SELL use symmetric price
conversion.

### Mandatory partial windows and August diagnosis

| Window | Full TP2 | Engine partial + BE | Engine partial + profit-lock | R DD profit-lock |
|---|---:|---:|---:|---:|
| Jan 2025–now | **+121.30R** | +110.05R | +111.25R | 10.93R |
| Nov–Feb | **+33.47R** | +27.65R | +28.93R | 9.93R |
| Jun–now | **+13.99R** | +14.09R | +13.78R | 3.00R |
| Aug 4–19 tuning | +11.95R | **+12.04R** | +11.74R | 1.00R |

Sub-BEP improves January and November relative to direct-BEP partials because
some runners survive a normal retracement. It remains below full TP2 in both
windows, trails direct BEP in June and August, and does not pass the locked
partial-window gate. Increasing retained profit converges toward BEP; reducing
it converges toward the original stop, so no further fraction fitting is done
on the small August sample. This policy remains a shadow counterfactual only;
no full suite, runtime, or order mutation is authorized.

## SELL and shared-balance profit-lock diagnosis

The same 25% basket-lock formula was replayed symmetrically on Bear SELL. The
initial SELL test deliberately applied a universal 0.01/0.01 split so the
idea itself could be measured before inventing a SELL selector.

| SELL window | Full TP2 | Split profit-lock | R DD full/lock |
|---|---:|---:|---:|
| Jan 2025–now | **+29.57R** | +18.30R | 8.00 / 7.00 |
| Nov–Feb | **+8.67R** | +4.78R | 3.00 / 3.00 |
| Jun–now | **+6.00R** | +3.29R | 4.00 / 4.00 |
| Aug 4–19 | **+3.00R** | +1.72R | 1.00 / 1.00 |

SELL rarely reversed after TP1 in these samples: November had zero
stop-after-TP1 outcomes, June had one, and both August TP1 hits continued to
TP2. There is therefore no causal August subset from which to create a SELL
partial selector.

The portfolio replay was upgraded to represent TP1 and runner as separate
margin legs. A TP1 fill realizes its cash and releases 0.01 margin at the
causal M1 timestamp; the runner retains its own floating P/L and close time.
Both entry legs are admitted atomically as the original 0.02 position.

### One shared USD 100 balance, 0.02 BUY + 0.02 SELL

| Window | Full TP2 both | Profit-lock both | SELL lock only |
|---|---:|---:|---:|
| Jan 2025–now | **$1,737.45** | $1,432.21 | $1,612.19 |
| Nov–Feb | **$604.46** | **$1.67 stop-out** | $541.39 |
| Jun–now | **$330.95** | $275.56 | $273.71 |

Combining sides does not reverse the standalone decision. SELL profit-lock
reduces the accumulated buffer before later losses; in November, changing
both sides causes shared stop-out. These are diagnostic replays without
commission, swap, or slippage, so the rejected partial variant would not
improve after adding execution costs. Full TP2 remains selected for Bear.

## Fixed-lot cash-risk selective partial (no BEP)

At the user's requested USD 100,000 balance and 0.20 lot per engine, stop-out
is no longer the binding constraint. A diagnostic grouped the fixed-lot cash
effect of BUY partial candidates by entry risk relative to M5 ATR. Setups with
`abs(entry - stop) < 1.0 * M5_ATR` contributed +10.00R and approximately
+USD 478 versus full TP2, while every wider risk band lost cash.

The frozen research selector `ENGINE_PARTIAL_KEEP_STOP` requires:

- BUY RANGE confirmation;
- structural TP1 from 0.75R inclusive to below 1.00R;
- TP2/TP1 distance ratio at least 2;
- entry-to-stop distance below 1.0 M5 ATR.

It closes 0.01 at structural TP1 and leaves the 0.01 runner on the original
structural SL. It does **not** call `ENGINE_BE_AFTER_TP1`, does not move to
BEP/sub-BEP, and does not change Bear SELL.

### R replay

| Window | Full TP2 | Cash-risk partial keep-stop | DD full/candidate |
|---|---:|---:|---:|
| Jan 2025–now | +121.30R | **+122.67R** | 9.62 / 9.62R |
| Nov–Feb | +33.47R | **+33.67R** | 8.62 / 8.62R |
| Jun–now | **+13.99R** | +13.59R | 3.00 / 3.00R |
| Aug 4–19 | **+11.95R** | +11.54R | 1.00 / 1.00R |
| Full 2020–now | +180.94R | **+190.94R** | 29.50 / **27.56R** |

### Shared USD 100,000 balance, BUY 0.20 + SELL 0.20

SELL remains full TP2 in both columns.

| Window | Full TP2 balance | Candidate balance | Net improvement |
|---|---:|---:|---:|
| Jan 2025–now | $116,374.50 | **$116,563.74** | +$189.24 |
| Nov–Feb | $105,044.60 | **$105,125.70** | +$81.10 |
| Jun–now | $102,309.50 | **$102,312.74** | +$3.24 |
| Full 2020–now | $124,815.47 | **$125,293.60** | +$478.13 |

On the full shared replay, floating drawdown improves from $4,050.76 to
$3,951.24 and realized drawdown from $1,844.00 to $1,817.45. No stop-out or
margin failure occurs.

This is an **in-sample research candidate** because the `<1.0 M5 ATR` threshold
was selected after inspecting full-suite fixed-lot cash groups. The result
cannot be called out-of-sample or forward validated. Runtime/order behavior
remains unchanged; the next legitimate step is frozen forward shadow evidence
with execution-cost accounting.

### Shared USD 100 stress replay, BUY 0.02 + SELL 0.02

The same frozen cash-risk selector was rerun without scaling the USD 100,000
results. The portfolio was replayed event by event because margin and stop-out
are nonlinear at this balance.

| Window | Full TP2 balance | Candidate balance | Improvement | Candidate min equity |
|---|---:|---:|---:|---:|
| Jan 2025–now | $1,737.45 | **$1,756.02** | +$18.57 | $45.96 |
| Nov–Feb | $604.46 | **$612.49** | +$8.03 | $40.66 |
| Jun–now | $330.95 | **$331.25** | +$0.30 | $32.27 |
| Full 2020–now | $2,580.04 | **$2,627.93** | +$47.89 | $74.43 |

All requested positions close and no simulated margin failure or stop-out
occurs. On the full replay, floating drawdown improves from $405.09 to $395.13
and realized drawdown from $184.47 to $181.82. The result differs from earlier
portfolio experiments that used different report/policy inputs; this table uses
the current causal dual-TP reports and atomic-leg simulator.

USD 100 remains a high-risk stress profile. The June minimum equity of $32.27
leaves little protection against execution costs or an adverse tick path not
represented by conservative M1 OHLC ordering. This replay is not evidence that
0.02 lot is operationally safe on a live USD 100 account.

## Locked candidate comparison at USD 100

`BALANCED_V1` is frozen before the next search. A causal ATR-limit sweep then
produced a profit finalist and two attempted safety profiles. All use BUY
selective partial keep-stop, no BEP, and unchanged Bear full TP2.

| Candidate | Risk/ATR limit | Full ending | Floating DD | Realized DD | Minimum equity | Decision |
|---|---:|---:|---:|---:|---:|---|
| Full TP2 baseline | none | $2,580.04 | $405.09 | $184.47 | $74.42 | reference |
| `BALANCED_V1` | <1.00 | $2,627.93 | $395.13 | $181.82 | **$74.43** | locked comparator |
| `PROFIT_V1` | <1.10 | **$2,641.40** | **$395.13** | $181.82 | **$74.43** | **profit finalist** |
| Conservative | <0.75 | $2,596.45 | $405.09 | $181.82 | **$74.43** | rejected/dominated |
| Safety wide | effectively unbounded | $2,463.65 | **$389.28** | **$166.48** | $69.83 | rejected as operational safety |

The wide profile minimizes absolute historical drawdown only by removing too
much accumulated profit. Its drawdown percentage worsens to 15.63% and minimum
equity falls below baseline, so it is not accepted as a genuinely safer USD
100 candidate. The conservative profile does not reduce floating drawdown and
is dominated by `PROFIT_V1`. No separate safety candidate passes all of profit,
drawdown percentage, and minimum-equity checks.

### Independent USD 100 partial windows

Every row starts from a fresh USD 100 balance.

| Window | Full TP2 | `BALANCED_V1` | `PROFIT_V1` | Safety wide |
|---|---:|---:|---:|---:|
| Jan 2025–now | $1,737.45 | $1,756.02 | **$1,773.30** | $1,611.80 |
| Nov–Feb | $604.46 | **$612.49** | **$612.49** | $537.40 |
| Jun–now | $330.95 | **$331.25** | **$331.25** | **$331.25** |
| Full 2020–now | $2,580.04 | $2,627.93 | **$2,641.40** | $2,463.65 |

`PROFIT_V1` adds $13.47 over `BALANCED_V1` on the full replay without worsening
its floating drawdown, realized drawdown, or minimum equity. It remains
in-sample because 1.10 was selected from this ATR sweep. Both locked candidates
are shadow-only and require execution-cost stress plus frozen forward evidence.

### Independent 1–19 August 2026 check

Both variants start from a fresh USD 100 balance with BUY 0.02 and SELL 0.02.
No position or profit is carried in from July.

| Metric | Full TP2 baseline | `PROFIT_V1` |
|---|---:|---:|
| Ending balance | $261.19 | **$261.49** |
| Net profit | $161.19 | **$161.49** |
| Floating DD | $40.00 | $40.00 |
| Floating DD percentage | 14.78% | **14.69%** |
| Realized DD | $20.02 | $20.02 |
| Minimum equity | $87.65 | $87.65 |
| Underlying setups | 14 | 14 |

`PROFIT_V1` improves the August window by $0.30 without changing absolute
drawdown or minimum equity. Its extra ledger positions are TP1/runner legs from
three split setups, not additional signals.

### August USD 50/30 with 0.01 lot per engine

The broker volume step is 0.01. A total 0.01 position cannot execute the
strategy's 50/50 partial because 0.005/0.005 legs are invalid. The simulator
therefore falls back atomically to one full 0.01 runner; it never rounds both
legs up and doubles exposure.

| Start balance | Lot BUY/SELL | Baseline ending | `PROFIT_V1` ending | Minimum equity | Stop-out |
|---:|---:|---:|---:|---:|---|
| $50 | 0.01 / 0.01 | $130.63 | $130.63 | $43.83 | no |
| $30 | 0.01 / 0.01 | $110.63 | $110.63 | $23.83 | no |

Both rows cover the independent 1–19 August 2026 window and start from the
listed fresh balance. Net profit is $80.63 in each because fixed lot and the
trade sequence are identical. `PROFIT_V1` records three non-executable partial
fallbacks and therefore has exactly the same P/L and drawdown as full TP2.
Its partial advantage begins only when total volume is at least 0.02.

### August realized-balance step-up sizing

This replay selects lot at each new entry from realized balance:

- below USD 100: 0.01;
- at or above USD 100: 0.02;
- downgrade back to 0.01 if realized balance falls below USD 100;
- an already-open position is never resized.

Each row independently covers 1–19 August 2026. BUY and SELL use the same lot
step, and `PROFIT_V1` partials remain executable only on 0.02 trades.

| Start | Adaptive baseline ending | Adaptive `PROFIT_V1` ending | Low/high-lot trades | Minimum equity | Stop-out |
|---:|---:|---:|---:|---:|---|
| $100 | **$239.25** | $235.86 | 3 / 11 | $89.29 | no |
| $50 | **$130.17** | $126.78 | 12 / 2 | $43.83 | no |
| $30 | **$110.17** | $106.78 | 12 / 2 | $23.83 | no |

The USD 50 and USD 30 paths first step up on 18 August 2026 at 02:43 broker
time. Two selected partials occur while size is still 0.01 and correctly fall
back to a full runner; one occurs at executable 0.02. On this short sequence,
that partial reduces ending balance by $3.39 versus the adaptive full-TP2
baseline. Immediate step-up is therefore not selected from this August sample,
although every path completes without simulated margin failure.

### Step-up sizing across the four other windows

All rows independently reset to the stated balance. Lot is 0.01 below USD 100
and 0.02 at or above USD 100, with automatic downgrade. The table shows ending
balance; `SO` means shared-portfolio stop-out before reaching the threshold.

| Window | Start | Adaptive baseline | Adaptive `PROFIT_V1` | Difference | Minimum equity |
|---|---:|---:|---:|---:|---:|
| Jan 2025–now | $100 | $1,685.44 | **$1,721.29** | +$35.85 | $66.65 |
| Jan 2025–now | $50 | $1,621.61 | **$1,657.46** | +$35.85 | $22.99 |
| Jan 2025–now | $30 | $1,583.42 | **$1,616.33** | +$32.91 | **$2.99** |
| Nov–Feb | $100 | **$592.88** | $589.79 | -$3.09 | $64.99 |
| Nov–Feb | $50 | **$468.05** | $464.96 | -$3.09 | **$6.00** |
| Nov–Feb | $30 | **$0.84 SO** | **$0.84 SO** | $0.00 | $0.33 |
| Jun–now | $100 | $242.11 | **$265.99** | +$23.88 | $52.79 |
| Jun–now | $50 | **$228.66** | $225.27 | -$3.39 | $16.13 |
| Jun–now | $30 | **$0.824 SO** | **$0.824 SO** | $0.00 | -$3.87 |
| Full 2020–now | $100 | $2,563.99 | **$2,625.35** | +$61.36 | $86.56 / $86.57 |
| Full 2020–now | $50 | $2,477.09 | **$2,538.44** | +$61.35 | $37.25 |
| Full 2020–now | $30 | $2,350.74 | **$2,409.44** | +$58.70 | $17.25 |

Underlying low/high-lot trade counts for baseline are:

- Jan: 17/342 from $100, 36/323 from $50, and 46/313 from $30;
- Nov–Feb: 22/58, 40/40, and 23/0 before the $30 stop-out;
- Jun: 18/15, 23/10, and 9/0 before the $30 stop-out;
- Full: 12/1253, 27/1238, and 82/1183.

`PROFIT_V1` improves the full and January paths at every tested start, and the
June USD 100 path. It loses slightly in November and in June from USD 50.
USD 30 fails two mandatory start windows before any step-up, despite surviving
the full suite after early-history compounding. USD 30 is therefore rejected as
a generally safe starting balance; USD 50 also has critically low equity in
November and is not robust to execution costs.
