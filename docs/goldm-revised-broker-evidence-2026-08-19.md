# GOLDM_REVISED 0.5.0 — broker chart evidence

## Scope

This is a visual and causal reconciliation against the production MT5
`GOLD.i#` M15 chart. It is not a parameter sweep or a replacement backtest.
Production `GOLDM_SNIPER_PARITY` and `goldm_bear` remain unchanged.

## Locked evidence outcomes

1. **17 August 18:30 server / about 22:34 WIB — SELL candidate.**
   The broker candle was O 4425.49, H 4426.41, L 4418.84, C 4419.23. A stale
   BUY must expire after the bearish reversal. The new bearish M5 hypothesis
   starts its own M1 confirmation and remains SELL observation-only.
2. **18 August about 02:15 server — BUY candidate.**
   Directional higher lows and expanding bullish displacement remain eligible
   for the momentum path.
3. **18 August about 03:15 server — SELL candidate.**
   A BUY micro-break at the 4434–4435 exhaustion area must expire when the
   bearish M5 reversal closes. The SELL hypothesis is evaluated independently.
4. **18 August about 09:15 server — SCALPER BUY.**
   The direction was correct but the late entry had only about 0.28R room. It
   is labeled `SCALPER`, tracked as observation-only, and excluded from the
   official core-BUY forward gate.
5. **18 August about 12:45 server — normal BUY.**
   The approximately 1.66R room remains eligible, with the target buffered
   before the 4400–4404 psychological/resistance cluster.

## Version 0.5.0 behavior

- A newly closed opposite M5 setup immediately expires the stale active side.
- The opposite setup is retained and builds a new causal M1 window; SELL is
  still `OBSERVATION_ONLY` in the initial rollout.
- Entry risk may tighten from broad M5 invalidation to the nearest *confirmed*
  M1 structural pivot after the trigger.
- The adaptive stop has an ATR/spread minimum distance and is used only when it
  is directionally valid and tighter than the original invalidation.
- `firstObstacleR >= 1` is still mandatory after stop selection.
- Targets remain buffered before the first horizontal or psychological
  obstacle. No target or threshold is stretched to manufacture a valid trade.
- Strong M5 rejection and three-candle morning/evening-star patterns are
  recognized symmetrically. A bare micro-break remains non-strong.
- Core BUY signals retain the 1R first-obstacle gate. A separately labelled
  `SCALPER` BUY may be shadow-tracked from 0.25R, requires a strong M5 pattern
  plus all three M1 votes and a micro-break, and never sends an admin entry
  notification or enters core forward metrics.
- Core target buffering is increased from 0.08 ATR to 0.12 ATR so evidence
  number 5 targets slightly below the resistance/psychological cluster.

These behaviors are regression-tested before any broker replay or forward test.

## Broker replay verdict for 0.4.0

Targeted replay from 17–19 August on broker `GOLD.i#` did **not** pass:

- signals: 3, all SCALPER BUY;
- core BUY: 0;
- SELL: 0;
- outcomes: 2 targets and 1 stop;
- total: -0.2886R;
- expectancy: -0.0962R;
- maximum drawdown: 1R.

Evidence reconciliation also failed:

- evidence 1 created SELL hypotheses, but they were cancelled at approximately
  0.16R and 0.03R first-obstacle room with only one M1 vote;
- evidence 2 produced a SELL hypothesis near the inspected time, not the
  required core BUY;
- evidence 3 and evidence 5 had no matching setup within the five-minute
  inspection tolerance;
- evidence 4 briefly reached BUY `WATCH` with about 1.12R room, but M1 had zero
  votes; the next evaluation collapsed to about 0.11R and cancelled the setup
  before it could become SCALPER.

Version 0.4.0 is therefore research-only and must not be enabled for shadow or
forward testing. The next investigation must address timestamp/setup alignment,
avoid immediate cancellation while a valid SCALPER M1 window is still pending,
and prevent already-accepted micro-swings from becoming false first obstacles.

## Multi-retest WATCH revision

Version 0.5.0 changes confirmation lifecycle without relaxing hard safety:

- a first failed validation or temporarily insufficient obstacle room becomes
  `WATCH_ONLY` or `SOFT_FAIL`, not immediate rejection;
- the setup remains causal and restart-safe for up to 60 closed M1 candles;
- Fibonacci 38.2–61.8% is derived from the ordered M5 impulse before trigger;
- distinct Fibonacci retests must be separated by at least two M1 candles and
  price must leave the zone before another retest is counted;
- a strong first validation may still enter through the existing momentum path;
- only two closes beyond setup invalidation, or three of four displaced closes,
  produce `HARD_INVALIDATION_ACCEPTED`;
- WATCH notifications are idempotent per validation status and retest number;
- ENTRY and final rejection notifications remain separate state transitions.
