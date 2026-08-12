# GoldM Sniper v1.6 — relaxed confluence and Fibonacci projection

Date: 2026-08-12
Symbol: `GOLD.i#`
Mode: signal-only
Evaluation boundary: no period before `2026-07-01` was evaluated for this version.

## Algorithm

### M15 setup and risk

- D1/H4/H1 context uses a two-of-three directional vote instead of requiring all
  context layers to agree.
- M15 breakout, retest, ATR, structural invalidation, stop, and risk remain the
  primary calculation.
- Breakout/retest tolerances and entry distance are wider than v1.5.
- Minimum structural room is `1.5R`; target selection skips nearer objectives that
  cannot provide the minimum room.

### M5 confirmation

The following five independent observations vote instead of forming five mandatory
gates:

1. price action: rejection, engulfing, micro-break, morning doji star, or evening
   doji star;
2. RSI(14);
3. Stochastic(14,3,3);
4. Bollinger Bands(20,2);
5. Fibonacci retracement alignment.

Two votes are sufficient when at least one vote comes from price action, Bollinger,
or Fibonacci structure. Morning/evening doji star is a strong pattern bonus, not a
standalone order command.

### Fibonacci projection

- The impulse graph is built from the most recent 24 closed M15 candles and the
  M15 breakout extreme.
- Retracement observations: `23.6%`, `38.2%`, `50%`, `61.8%`, and `78.6%`, with a
  `6%` ratio tolerance.
- Extension projections: `127.2%`, `161.8%`, and `200%`.
- A non-aligned M1 entry may be delayed by at most one M1 candle. After that,
  otherwise-valid confluence can still act, so Fibonacci strengthens timing rather
  than becoming another hard filter.
- The nearest valid extension can act as a target candidate and as a reaction zone
  where one opposing M1 management candle is sufficient to close.

This is a deterministic price projection. It is not a calibrated probability and
does not imply that a Fibonacci level must hold.

### M1 timing and close

- M1 directional candle, micro-break, and RSI provide timing votes.
- M5 confluence of at least three votes may use a fallback entry if M1 remains
  imperfect but M15 invalidation is still held.
- After reaching +1R, the signal protects approximately +0.25R; after +2R it
  protects approximately +1R. M1 reversal management can close earlier.

## Verification

- MetaEditor: `0 errors, 0 warnings`.
- Python tests: `19 passed`.
- No order execution API is present in the parity EA.
- Tests used MT5 real-tick model only for `2026-07-01` onward.

## Results with maximum one-M1-bar Fibonacci delay

| Window | Signals | P1 | P2 | P3 | Total R | Expectancy |
|---|---:|---:|---:|---:|---:|---:|
| 2026-07-01 to 2026-08-01 | 39 | 48.72% | 2.56% | 0.00% | -5.69834R | -0.14611R |
| 2026-08-01 to 2026-08-12 | 13 | 38.46% | 7.69% | 0.00% | -3.69088R | -0.28391R |

July produced 48 Fibonacci-delayed M1 bars and two aligned final entries. August
produced 15 delayed bars and one aligned final entry. The method successfully
widens setup admission compared with v1.5, but Fibonacci alignment has not produced
positive or stable expectancy in these limited windows.

## Decision

Keep this version research-only and signal-only. Fibonacci projection is available
as supporting evidence and close planning, but its current sample does not justify
calling it a successful probability model or enabling live/Telegram promotion.
