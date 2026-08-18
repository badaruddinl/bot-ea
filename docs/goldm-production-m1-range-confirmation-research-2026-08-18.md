# GOLDM production M1 range-confirmation research — 2026-08-18

## Interpretation of the proposed behavior

The proposal is understood as a stateful confirmation process rather than a
single-candle pattern:

1. M5 creates the directional setup and level.
2. M1 observes how price behaves around that level and inside the local range.
3. Repeated *successful rejection* of a boundary strengthens the setup.
4. Repeated penetration or time spent outside the boundary is acceptance, not
   confirmation.
5. Strong directional momentum may bypass the repeated-touch requirement.
6. When momentum decelerates or exhausts, the engine must return to range-touch
   confirmation before entry.

This remains a production-baseline research design. It does not import or reuse
the standalone `goldm_bear` engine.

## Why one M1 candle is insufficient

The current `ProcessClosedM1()` uses:

- held invalidation; and
- any two votes from directional candle, micro-break, and RSI side of 50.

It does not measure how long M5/M1 has ranged, how many distinct level tests
occurred, whether price repeatedly returned inside, or whether the breakout was
accepted for multiple closes. `microBreak` is optional. At the M1 bar limit,
fallback can create a signal without refined M1.

The live evidence confirms the weakness:

- confidence 92 at 17 August 22:34 WIB had `m1Confirmed=false` and lost -1R;
- a true-M1 BULL_ENGULFING around 07:00 WIB returned +0.2184R;
- a true-M1 BULL_MICRO_BREAK around 08:00 WIB lost -1R;
- a true-M1 BULL_REJECTION with only 0.28R obstacle room around 14:00 WIB lost;
- a lower-score true-M1 BULL_REJECTION with 1.66R room around 17:30 WIB returned
  +1.2687R.

M1 confirmation must therefore describe both the *path* and available room.

## Microstructure interpretation

Support/resistance levels have empirically predicted intraday interruptions,
but not every hit is a bounce: [FRBNY, *Support for Resistance*](https://www.newyorkfed.org/research/epr/00v06n2/0007osle.html).
Round-price clustering can create real barriers in an electronic FX order book:
[Lallouache and Abergel, *Tick Size Reduction and Price Clustering*](https://arxiv.org/abs/1307.5440).

At short horizons, price changes are more closely related to order-flow
imbalance and available depth than raw transaction volume alone:
[Cont, Kukanov, and Stoikov, *The Price Impact of Order Book Events*](https://arxiv.org/abs/1011.6402).
During high-volatility, one-sided-flow episodes, positive feedback and momentum
can dominate normal reversal behavior: [BIS Working Paper 122](https://www.bis.org/publ/work122.pdf).

Because spot broker M1 bars do not expose the full order book, the engine must
use causal price-action proxies for rejection, acceptance, momentum, and
exhaustion. These papers motivate the states; they do not prove the proposed
thresholds for `GOLD.i#`.

## Proposed causal measurements

All measurements use closed M1 bars only.

### Local M1 range

- Observation window: from the M5 trigger, minimum 4 and maximum 12 M1 bars.
- Range high/low: highest high and lowest low in the window.
- Range width: `rangeHigh - rangeLow`.
- Normalized width: range width divided by M1 ATR(14) and M15 ATR(14).
- Dwell: number of closed M1 bars since the M5 trigger.

The initial tolerance candidate is:

```text
touchTolerance = max(2 × spread, 0.10 × M1_ATR, 0.03 × M15_ATR)
```

### Distinct touch

A touch is counted only if:

- high/low enters the boundary tolerance;
- it is separated from the previous touch by at least two closed M1 bars; and
- price retreated at least 0.25 of the local range after the previous touch.

This prevents five ticks or adjacent candles at the same boundary from being
misreported as five independent confirmations.

### Successful rejection

For BUY support:

- low touches support tolerance;
- close returns above support plus 0.10 range;
- the next excursion bounces at least 0.30 range; and
- no two consecutive closes are below support.

SELL resistance is symmetric.

Repeated touches strengthen the setup only when their rejection excursion does
not decay sharply. Repeated contact with smaller bounces is interpreted as
liquidity consumption/exhaustion, not stronger support.

### Acceptance outside the range

A boundary is accepted when either:

- two consecutive M1 closes occur outside it; or
- three of four closes are outside and net displacement exceeds 0.50 M1 ATR.

Acceptance cancels a reversal entry at that boundary. It may instead validate a
momentum breakout after a retest from the other side.

## Hybrid state machine

```text
M5_SETUP
   ├─ strong directional expansion ──> M1_MOMENTUM
   │                                      ├─ persists ──> ENTRY_GATE
   │                                      └─ exhausts ──> M1_RANGE_BUILD
   └─ slow/ranging development ──────> M1_RANGE_BUILD
                                          ├─ rejected touches ──> RANGE_CONFIRMED
                                          ├─ accepted outside ──> CANCEL/FLIP
                                          └─ unresolved timeout ──> EXPIRE

RANGE_CONFIRMED or M1_MOMENTUM
   └─ first-obstacle room + final risk gate ──> ENTRY READY
```

### M1_MOMENTUM entry candidate

Momentum may bypass repeated touches only when all are true:

- at least two consecutive directional closes;
- net displacement at least 0.80 M1 ATR over the last three bars;
- latest close in the directional outer 25% of its range;
- body/range at least 0.55;
- range is expanding, not contracting;
- no opposite wick larger than the candle body; and
- first-obstacle room is at least 1.5R.

### Momentum exhaustion

Momentum switches back to M1_RANGE_BUILD when at least two occur:

- directional displacement falls for two consecutive bars;
- body/range contracts below 0.35;
- opposite wick exceeds 0.50 of the full range;
- no new directional extreme exceeds the old extreme by 0.10 M1 ATR;
- RSI7 stops improving or crosses back through 50; or
- price closes back inside the prior three-bar range.

This implements the requested behavior: momentum gets a fast path, but once it
is nearly exhausted the engine cannot continue promoting on old momentum.

### M1_RANGE_BUILD entry candidate

The first diagnostic candidate requires:

- at least two distinct successful touches at the relevant support/resistance;
- at least one complete range excursion of 0.50 range or more;
- final micro-break mandatory;
- final close in the directional outer 35%;
- body/range at least 0.35;
- RSI7 on the correct side and improving; and
- no acceptance outside the invalidation boundary.

## First-obstacle gate remains mandatory

Range confirmation does not make an entry valid if the nearest obstacle leaves
no reward space:

- `<1.0R`: reject;
- `1.0–1.5R`: require three M1 votes, strong M5 pattern, and TP before obstacle;
- `>=1.5R`: normal target search is allowed.

This prevents M1 touch count from merely increasing confidence on the 0.28R-room
loss observed around 14:00 WIB.

## Diagnostic backtest matrix

The following variants should be evaluated without changing production:

| Variant | M1 logic | Momentum bypass | Obstacle gate |
| --- | --- | --- | --- |
| A | Current 2-of-3 + fallback | No | Current target logic |
| B | Micro-break mandatory, no fallback | No | Current target logic |
| C | Two distinct range rejections | No | Current target logic |
| D | Two range rejections | Yes, no exhaustion switch | First-obstacle gate |
| E | Two range rejections | Yes, returns to range on exhaustion | First-obstacle gate |

Report separately:

- BUY and SELL signal counts;
- fallback/refined/range/momentum entry counts;
- latency from M5 trigger to entry;
- missed move rate while waiting for a second touch;
- first-obstacle hit, original TP hit, STOP, MFE, and MAE;
- early-close shadow result; and
- results by `rangeTouchCount`, `rangeCycleCount`, and momentum state.

Known data through 18 August is diagnostic only. Variant selection must not use
the forward period beginning 19 August; that period is reserved for new evidence.

## Research conclusion

The proposed idea is technically coherent and addresses a real gap in the
baseline. The correct abstraction is not “touch twice means enter,” but:

```text
repeated rejected touches + meaningful excursion = range evidence
repeated penetration/time outside = acceptance
strong expansion = momentum fast path
deceleration/exhaustion = return to range evidence
```

The next implementation should add observation-only counters and shadow
decisions first. It should not yet alter Telegram promotion or production entry.
