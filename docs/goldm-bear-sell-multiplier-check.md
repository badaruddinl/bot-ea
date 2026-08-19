# goldm_bear v4 — SELL stop/target multiplier check

## Compared setups

All use v4 H1→M15→M5→M1 entries, USD 100 starting balance, and fixed 0.02 lot.

1. `NORMAL_EXACT_2R`: structural stop 1×; target exactly 2R from that stop.
2. `MULT_1.75_2`: stop distance 1.75×; target distance 2× the original
   structural target distance.
3. `MULT_2_2`: stop distance 2×; target distance 2× the original structural
   target distance.

## Mandatory initial three partial windows

| Window | Setup | Total R | Expectancy | R DD | Ending balance | PF | Cash DD | Result |
|---|---|---:|---:|---:|---:|---:|---:|---|
| Jan 2025–now | Normal exact 2R | **+25.00R** | **+0.338R** | **4.00R** | **$458.91** | **1.55** | **28.16%** | completed |
| Jan 2025–now | 1.75× : 2× | +17.74R | +0.246R | 7.49R | $407.93 | 1.36 | 71.54% | completed |
| Jan 2025–now | 2× : 2× | +14.44R | +0.206R | 7.55R | $398.75 | 1.33 | 82.78% | completed |
| Nov–Feb | Normal exact 2R | +7.00R | +0.412R | 4.00R | $229.52 | 1.81 | **34.91%** | completed |
| Nov–Feb | 1.75× : 2× | **+8.87R** | **+0.522R** | **3.00R** | $272.46 | 1.77 | 41.69% | completed |
| Nov–Feb | 2× : 2× | +7.88R | +0.493R | **3.00R** | **$284.11** | **1.87** | 42.64% | completed |
| Jun–now | Normal exact 2R | **+9.00R** | **+0.600R** | **2.00R** | **$258.03** | **2.22** | 36.83% | completed |
| Jun–now | 1.75× : 2× | +2.22R | +0.148R | 4.00R | **$1.65** | 0.36 | 71.15% | **stop-out** |
| Jun–now | 2× : 2× | +0.88R | +0.063R | 4.00R | **$1.65** | 0.32 | 87.09% | **stop-out** |

The multipliers improve November but are materially weaker in January and both
fail the June cash path. Normal exact 2R is the only setup that completes all
three partial windows.

## 4–19 August development evidence

| Setup | Trades | TP / SL | Total R | Ending balance | Cash DD |
|---|---:|---:|---:|---:|---:|
| 1.75× : 2× | 3 | 3 / 0 | +2.18R | $168.92 | 0% |
| 2× : 2× | 3 | 3 / 0 | +1.90R | $168.92 | 0% |

Both variants hit the same doubled target prices, so fixed-lot USD profit is
identical. The 1.75× stop reports higher R only because its risk denominator is
smaller. August contains no failed multiplier setup that can justify a causal
parameter adjustment.

## Decision

Keep SELL normal structural stop with exact 2R. Do not adopt 1.75×:2× or 2×:2×.
Per the mandatory validation order, no promising August adjustment was found,
so the multiplier experiment stops before repeated partial validation and full
suite.
