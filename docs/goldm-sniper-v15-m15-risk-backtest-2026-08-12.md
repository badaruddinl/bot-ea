# GoldM Sniper v1.5 — M15-native risk backtest

Date: 2026-08-12
Symbol: `GOLD.i#`
Tester host timeframe: `M15`
Tester model: `4` (real ticks)
EA mode: signal-only; no order functions

## Calculation change

- The hard stop is derived from the M15 breakout level, accepted M15 retest extreme,
  M15 ATR, and M15 invalidation allowance.
- M1 remains an entry-timing and post-1R management confirmation only. Its candle
  high/low no longer defines the stop or projected R.
- An entry must remain on the breakout side and no farther than `0.30 ATR(M15)`
  from the M15 level.
- Pending M5/M1 setups are invalidated if a later M15 close breaks the structural
  invalidation boundary.
- Projected R uses the nearest M15 structural objective and the M15-native stop.
- Breakout score components are now derived from M15 body, displacement, wick,
  relative tick volume, and retest distance instead of a nearly fixed checklist.

## Verification

- MetaEditor: `0 errors, 0 warnings`.
- Focused Python/unit tests: `13 passed`.
- The parity EA contains no `CTrade`, `OrderSend`, `Buy`, `Sell`, or position-open
  call.

## Results

| Window | M1-refined trigger candidates | M1 expired | M15 entry-distance rejected | M15 room rejected | Signals |
|---|---:|---:|---:|---:|---:|
| 2025-03-01 to 2025-09-01 | 62 | 14 | 46 | 2 | 0 |
| 2025-09-01 to 2026-01-01 | 79 | 23 | 56 | 0 | 0 |
| 2026-05-01 to 2026-08-01 | 33 | 12 | 21 | 0 | 0 |
| 2026-08-01 to 2026-08-12 | 2 | 1 | 1 | 0 | 0 |

In the 2025 research window, the two candidates that remained close enough to the
M15 level had projected room of only `0.54749R` and `0.85778R`. Neither reached the
required `3R` structural room.

## Interpretation

The previous 3R projections were not supported by M15 structure. They were created
mainly by dividing the available reward by a very small M1 stop. With an M15-native
stop and nearest M15 objective, the same setup family has no qualifying 3R signal in
the tested windows. The former losing SELL signal on 2026-07-20 is rejected before
scoring because its final entry is too far from the M15 breakout level.

This version should remain research-only. A future strategy iteration must change
the setup or entry mechanism to obtain a materially better entry near the M15 level;
loosening the M15 stop calculation or relabeling the score would recreate the same
false reward/risk inflation.
