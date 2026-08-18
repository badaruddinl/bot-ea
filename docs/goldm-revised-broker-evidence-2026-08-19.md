# GOLDM_REVISED 0.2.0 — broker chart evidence

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
4. **18 August about 09:15 server — early-structure BUY.**
   The direction was correct but the late entry had only about 0.28R room. It
   is valid only when a causal confirmed M1 structural stop and earlier entry
   recalculate first-obstacle room to at least 1R. The 1R gate is not relaxed.
5. **18 August about 12:45 server — normal BUY.**
   The approximately 1.66R room remains eligible, with the target buffered
   before the 4400–4404 psychological/resistance cluster.

## Version 0.2.0 behavior

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

These behaviors are regression-tested before any broker replay or forward test.
