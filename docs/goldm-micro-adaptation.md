# GOLDm# micro-contract adaptation

## Isolation

The GOLD.i# research milestone is immutable at commit `cd609e0` and annotated
tag `goldi-profit-v1-research-20260819`. This GOLDm# profile is a separate,
uncommitted adaptation until its native MT5 symbol is available and validated.

## Contract mapping

| Property | GOLD.i# research symbol | GOLDm# micro symbol |
|---|---:|---:|
| Contract size | 100 oz/lot | 1 oz/lot |
| Minimum lot | 0.01 | 0.1 |
| Minimum exposure | 1 oz | 0.1 oz |
| Spread floor | $0.20 | $0.24 |

Exposure-equivalent mapping is GOLD.i# 0.01 = GOLDm# 1.0 and GOLD.i# 0.02 =
GOLDm# 2.0. The selected micro-safe GOLDm# profile instead uses 0.1 below a
USD 100 realized balance and 0.2 at or above it. It therefore carries one
tenth of the previously tested exposure.

At 0.2, TP1 can close 0.1 and leave a 0.1 runner. This makes partial execution
available at 0.2 oz, whereas GOLD.i# needs 2 oz total exposure for its minimum
0.01/0.01 split.

## Engine behavior

Price/structure logic is unchanged: RANGE confirmation, structural TP1 from
0.75R to below 1.0R, TP2/TP1 ratio at least 2, risk below 1.10 M5 ATR, and the
runner retaining its original structural stop. No BEP is used. The symbol,
contract, volume grid, exposure, spread floor, and cash/margin calculations are
instrument-specific.

## Mandatory validation before replay or runtime

Run `py -3.14 scripts/validate-goldm-micro-symbol.py` against the terminal that
owns GOLDm#. The terminal on XMGlobal-MT5 14 verifies contract size 1, volume
minimum 0.1, **volume step 0.01**, price/tick size 0.01, tick value 0.01, and
volume maximum 100. The minimum and step are different; sizing must never infer
the step from the minimum trade size.

After validation, obtain native GOLDm# M1/M5/H1/D1 history and rerun the five
windows independently. GOLD.i# cash results cannot be rescaled and presented
as GOLDm# backtests because spread, ticks, symbol history, and executable volume
are broker-specific.

## Native history and partial-window result

XMGlobal-MT5 14 exposes native GOLDm# coverage from 2 December 2019 through
19 August 2026: 2,374,353 M1 bars, 475,356 M5 bars, 39,633 H1 bars, and 1,733
D1 bars. All research below uses these bars.

BUY uses the REVISED engine with spread floor 0.24, execution stop 1.75, and
target 2.5. SELL uses Bear v4 exact 2R. Shared sizing is 0.1 below USD 100 and
0.2 at/above USD 100, with downgrade below the threshold.

### Native BUY R result

| Window | Full TP2 | Reused 1.10 selector | Tuned 0.75 selector | DD |
|---|---:|---:|---:|---:|
| Jan 2025–now | +124.60R | **+125.14R** | +124.03R | 9.63R |
| Nov–Feb | +29.12R | **+29.33R** | +28.38R | 8.63R |
| Jun–now | +13.49R | +13.12R | **+14.40R** | 3.00R |
| Aug 1–19 | +11.43R | +11.06R | **+12.34R** | 1.00R |

The GOLD.i# 1.10 threshold improves Jan/Nov but degrades June/August. Tuning
on August selects a 0.75 threshold that improves June/August but degrades
Jan/November. Neither partial selector is accepted as the native primary.

### Native shared balance

| Window | Start | Full TP2 baseline | 0.75 partial shadow | Decision |
|---|---:|---:|---:|---|
| Jan | $100 | $257.60 | **$258.00** | shadow better |
| Jan | $50 | $157.40 | **$157.80** | shadow better |
| Jan | $30 | $118.86 | **$119.58** | shadow better |
| Nov–Feb | $100 | **$141.48** | $141.16 | baseline better |
| Nov–Feb | $50 | $73.14 | $73.14 | equal; 0.1 fallback |
| Nov–Feb | $30 | $53.14 | $53.14 | equal; 0.1 fallback |
| Jun | $100 | $119.27 | **$119.99** | shadow better |
| Jun | $50 | $61.82 | $61.82 | equal; 0.1 fallback |
| Jun | $30 | $41.82 | $41.82 | equal; 0.1 fallback |
| Aug | $100 | $110.32 | $110.32 | equal cash |
| Aug | $50 | $56.43 | $56.43 | equal; 0.1 fallback |
| Aug | $30 | $36.43 | $36.43 | equal; 0.1 fallback |

All rows complete without stop-out. Minimum equity remains materially healthier
than the old 1/2 oz exposure. The selected native profile is therefore
`GOLDm_MICRO_BASELINE_V1`: full TP2 on both sides with micro step-up sizing.
The 0.75 partial candidate is retained as rejected shadow evidence only.

## Native multi-tier sizing comparison

Three full-TP2 sizing profiles were compared on Jan, Nov–Feb, June, and
August, each independently starting at USD 100/50/30/10:

- Moderate: 0→0.5, 100→1.0;
- Aggressive: 0→0.1, 10→0.2, 30→0.5, 50→1.0, 100→2.0;
- Hybrid: the aggressive low tiers, but capped at 1.0 from USD 50 upward.

All lot decisions use realized balance and downgrade automatically.

### Ending balance by profile

| Window/start | Moderate | Aggressive | Hybrid |
|---|---:|---:|---:|
| Jan / $100 | $886.85 | **$1,673.27** | $908.18 |
| Jan / $50 | $795.31 | **$1,557.37** | $836.85 |
| Jan / $30 | $759.16 | **$1,423.24** | $779.61 |
| Jan / $10 | **$0.27 SO** | **$1,164.13** | $662.21 |
| Nov / $100 | $307.22 | **$514.31** | $330.91 |
| Nov / $50 | $205.08 | **$301.93** | $257.22 |
| Nov / $30 | $173.64 | **$205.08** | $167.84 |
| Nov / $10 | **$0.42 SO** | $101.20 | $101.20 |
| Jun / $100 | $196.17 | **$292.28** | $217.90 |
| Jun / $50 | $108.78 | **$168.79** | $146.17 |
| Jun / $30 | **$88.99** | $83.76 | $83.76 |
| Jun / $10 | **$0.446 SO** | $27.44 | $27.44 |
| Aug / $100 | $151.53 | **$203.05** | $164.25 |
| Aug / $50 | $82.13 | $101.10 | **$101.53** |
| Aug / $30 | **$62.13** | $36.15 | $36.15 |
| Aug / $10 | **$42.13** | $20.32 | $20.32 |

Moderate is not viable from USD 10 because its minimum 0.5 lot causes three
stop-outs. Aggressive survives every tested row and maximizes ending balance.
Its minimum equity falls as low as USD 4.15 and maximum floating drawdown on
the Jan path reaches USD 475.44, but the USD 4.15 trough occurs after automatic
downgrade to 0.1 lot and still has 592.10% margin level versus the broker's 20%
stop-out threshold. It is margin-safe in these replays, while remaining the
highest-drawdown and highest-exposure profile.

Hybrid survives every row, protects small balances using 0.1/0.2 tiers, and
caps exposure at 1 oz. Relative to aggressive it sacrifices profit but cuts
the Jan maximum floating drawdown from USD 475.44 to USD 237.70. It is the only
multi-tier finalist advanced to a future full-suite check. The existing
0.1/0.2 micro-safe baseline remains the selected conservative primary until
that check is complete.

### Minimum realized balance / minimum floating equity

Each cell is `minimum balance / minimum equity` in USD. Minimum balance only
changes on realized closes; minimum equity includes adverse open-position P/L.

Moderate:

| Window | Start $100 | Start $50 | Start $30 | Start $10 |
|---|---:|---:|---:|---:|
| Jan | 81.86 / 81.05 | 35.20 / 34.39 | 15.20 / 14.39 | **0.27 / 0.07 SO** |
| Nov–Feb | 84.24 / 72.84 | 43.18 / 31.78 | 23.18 / 11.78 | **0.42 / -1.44 SO** |
| Jun | 84.89 / 70.75 | 41.57 / 27.43 | 21.57 / 7.43 | **0.446 / 0.36 SO** |
| Aug | 95.43 / 94.61 | 47.72 / 46.90 | 27.72 / 26.90 | 7.72 / 6.90 |

Aggressive:

| Window | Start $100 | Start $50 | Start $30 | Start $10 |
|---|---:|---:|---:|---:|
| Jan | 63.74 / 62.12 | 31.86 / 31.05 | 22.08 / 21.76 | 6.37 / 6.21 |
| Nov–Feb | 68.47 / 45.66 | 23.66 / 7.89 | 19.99 / 7.52 | 6.85 / 4.57 |
| Jun | 69.74 / 41.45 | 34.89 / 20.75 | 22.64 / 14.83 | 6.98 / 4.15 |
| Aug | 90.86 / 89.22 | 45.43 / 44.61 | 27.21 / 25.53 | 9.09 / 8.93 |

Hybrid:

| Window | Start $100 | Start $50 | Start $30 | Start $10 |
|---|---:|---:|---:|---:|
| Jan | 70.43 / 68.81 | 31.86 / 31.05 | 22.08 / 21.76 | 6.37 / 6.21 |
| Nov–Feb | 86.34 / 63.53 | 34.24 / 22.84 | 19.99 / 7.52 | 6.85 / 4.57 |
| Jun | 83.09 / 54.80 | 34.89 / 20.75 | 22.64 / 14.83 | 6.98 / 4.15 |
| Aug | 95.43 / 93.79 | 45.43 / 44.61 | 27.21 / 25.53 | 9.09 / 8.93 |

The tables show why ending balance alone is insufficient. Aggressive and
Hybrid can finish strongly after recovering while temporarily leaving USD 4–8
equity from a USD 10 start. That trough is not itself a margin emergency: their
start-10 minimum margin levels are 1022.22%/1312.70% in Jan, 889.92% in
Nov–Feb, 592.10% in June, and 1093.49% in August. Moderate avoids some high-tier
risk but its 0.5 minimum lot is too large for USD 10 and produces actual
stop-outs before it can downgrade.

## Execution-cost stress test

MT5 reports floating spread, swap mode 0 (disabled), and observed spread around
0.26–0.30 USD. Three explicit round-trip stress levels were applied. Entry
spread/slippage/commission reduces balance immediately; exit slippage and
commission is charged at close.

| Level | Spread | Slippage per side | Commission per lot/side |
|---|---:|---:|---:|
| Observed | $0.30 | $0.02 | $0.00 |
| Severe | $0.60 | $0.05 | $0.10 |
| Extreme | $1.20 | $0.10 | $0.25 |

Each level covers Aggressive and Hybrid on Jan, Nov–Feb, June, and August from
fresh USD 100/50/30/10 balances (32 cases per level).

| Profile | Observed failures | Severe failures | Extreme failures | Stress decision |
|---|---:|---:|---:|---|
| Aggressive | 0 / 16 | 1 / 16 | 5 / 16 | observed-cost only |
| Hybrid | 0 / 16 | **0 / 16** | 5 / 16 | **severe-pass finalist** |
| Micro-safe 0.1→0.2 | not required | not required | **0 / 16** | **extreme-pass primary** |

Aggressive Severe fails Jan from USD 10. Under Extreme, both Aggressive and
Hybrid fail all four Jan starts and Nov from USD 10. Other Nov, June, and
August Extreme paths survive.

Hybrid Severe ending balances are:

| Window | Start $100 | Start $50 | Start $30 | Start $10 |
|---|---:|---:|---:|---:|
| Jan | $591.38 | $499.88 | $378.86 | $276.50 |
| Nov–Feb | $259.81 | $170.90 | $83.25 | $42.64 |
| Jun | $189.10 | $122.32 | $34.14 | $24.50 |
| Aug | $151.65 | $60.05 | $34.19 | $12.01 |

The micro-safe profile survives Extreme in every row. Its lowest case is
Nov–Feb from USD 10: ending balance USD 18.13, minimum equity USD 0.526, and
minimum margin level 125.24%, still above the 20% stop-out threshold. This is
margin-safe in the M1 replay but leaves very little cash buffer.

Dynamic tiers make ending balance path-dependent: higher costs can delay a
step-up into a larger lot, so a more expensive scenario can occasionally end
above a cheaper scenario. Failure count, minimum equity, and margin level take
priority over monotonic ending-balance expectations.

## Primary selection

The user explicitly selects Aggressive as the GOLDm# primary research sizing
profile:

```text
balance < 10   -> 0.1 lot
balance >= 10  -> 0.2 lot
balance >= 30  -> 0.5 lot
balance >= 50  -> 1.0 lot
balance >= 100 -> 2.0 lot
```

Sizing uses realized balance at entry and downgrades automatically. BUY and
SELL retain full TP2 management; no BEP or partial management is enabled.

The selection accepts its measured stress boundary: 16/16 observed scenarios,
15/16 severe scenarios, and 11/16 extreme scenarios pass. Severe fails Jan
from USD 10; Extreme fails all Jan starts and Nov from USD 10. Hybrid is the
secondary fallback and the 0.1→0.2 profile is the conservative fallback.

This changes research priority, not deployment state. Full-suite native GOLDm#
replay remains required, and runtime/order flags remain disabled until a
separate activation decision.

## Native full suite 2020–19 August 2026

The full native engine resolves 1,404 base BUY signals. Applying stop 1.75,
target 2.5, and overlap lock leaves 933 BUY trades with +175.04R, +0.188R
expectancy, and 28.16R drawdown. Bear v4 exact 2R contributes 308 SELL trades,
+88R, +0.286R expectancy, and 12R drawdown.

### Aggressive full-suite result

| Costs | Start $100 | Start $50 | Start $30 | Start $10 |
|---|---|---|---|---|
| No cost | $2,479.79 | $2,352.27 | $2,092.74 | $1,588.76 |
| Observed | $1,102.44 | $1,035.90 | **SO** | **SO** |
| Severe | **insufficient margin** | **insufficient margin** | **SO** | **SO** |
| Extreme | **insufficient margin** | **insufficient margin** | **insufficient margin** | **SO** |

At Observed cost, start USD 100 reaches minimum balance/equity 17.10/16.89;
start USD 50 reaches 1.81/1.42 but still completes. USD 30 and USD 10 stop out.
The user-selected Aggressive profile therefore passes the full observed gate
only for initial balance at least USD 50. It is not a universal primary.

### Full observed fallback comparison

| Profile | Start $100 | Start $50 | Start $30 | Start $10 |
|---|---:|---:|---:|---:|
| Aggressive | $1,102.44 | $1,035.90 | **SO** | **SO** |
| Hybrid | $871.93 | $674.40 | $615.17 | **SO** |
| Micro-safe 0.1→0.2 | $235.11 | $148.93 | $110.16 | $87.86 |

Hybrid extends observed eligibility to initial USD 30, but USD 10 still stops
out. Micro-safe is the only profile that completes full observed history from
all four starts. Its USD 10 path reaches minimum balance/equity 1.522/1.135 and
minimum margin level 533.25%.

Full severe costs defeat every Hybrid start. Full extreme costs eventually
leave micro-safe unable to fund the next minimum-lot entry at every start,
despite its partial-window extreme pass. This illustrates why partial-window
stress success cannot substitute for full-sequence cost validation.

The evidence-based routing recommendation is initial USD 50+ Aggressive,
initial USD 30 Hybrid, and below USD 30 micro-safe. This recommendation is not
enabled in runtime; orders remain disabled pending an explicit user decision.
