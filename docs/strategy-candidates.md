# Strategy Candidates

## Goal

List the most realistic strategy families to test first for an MT5 retail bot.

## Research basis

The strongest recurring findings from the research are:

- FX and many CFD markets are strongly `session-driven`
- volatility and spreads change materially around active opens and macro news
- guardrails matter more than adding many extra indicators
- MT5 can support these guardrails natively through session/calendar/spread/ATR primitives

Supporting sources:

- BIS FX market review  
  <https://www.bis.org/publ/work1094.pdf>
- NBER intraday FX seasonality  
  <https://www.nber.org/papers/w12413>
- NBER macro announcements and intraday FX volatility  
  <https://www.nber.org/papers/w5783>  
  <https://www.nber.org/papers/w8959>
- NBER volatility and bid-ask spreads  
  <https://www.nber.org/papers/w4737>
- MT5 session/calendar/ATR/tick-volume docs  
  <https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade>  
  <https://www.mql5.com/en/docs/calendar/calendarvaluehistorybyevent>  
  <https://www.mql5.com/en/docs/indicators/iatr>  
  <https://www.mql5.com/en/docs/series/ivolume>

## Selection criteria

A family is a good v1 candidate if it:

- is rule-based
- can be guarded by spread/session/news filters
- does not need many free parameters
- can survive realistic retail execution assumptions

## Candidate 1: Session Breakout

Best for:

- forex majors during liquid overlaps
- selected index CFDs around strong session transitions
- gold during active London/New York overlap windows

Why it is attractive:

- clear range definition
- clear breakout trigger
- natural session filter
- matches the documented clustering of activity around major session opens/overlaps

Main guardrails:

- spread cap
- volatility confirmation
- no trade near major scheduled news
- avoid low-liquidity windows
- reject if opening range is abnormally wide or abnormally dead

Main failure mode:

- fake-out breakout in noisy or thin conditions

## Candidate 2: Trend Pullback Continuation

Best for:

- liquid symbols with visible intraday directional structure

Why it is attractive:

- simple idea
- entries can be normalized with volatility
- compatible with strict risk sizing
- fits markets where impulse then retrace behavior appears after session/macro-driven expansion

Main guardrails:

- only trade with active trend filter
- reject choppy structure
- reject if pullback becomes reversal
- no-chase rule if price has already moved too far from the anchor move

Main failure mode:

- repeated entries into chop

## Candidate 3: Volatility Contraction Expansion

Best for:

- symbols that compress before impulsive moves

Why it is attractive:

- can be made very rule-based
- often works well with stop distance tied to volatility
- pairs well with active-session filters and post-compression expansion logic

Main guardrails:

- require compression first
- require expansion confirmation
- reject if spread is too large relative to expected move
- block around high-impact news, because pre-news compression can be misleading

Main failure mode:

- breakout without follow-through

## Candidate 4: Failed Breakout / Range Reversion

Best for:

- liquid symbols in non-trend conditions
- secondary use after stronger families are already understood

Why it is attractive:

- can be rule-based when a level sweep fails and price re-enters range
- naturally supports conservative targets

Main guardrails:

- only enable when trend-day conditions are absent
- do not run simultaneously with breakout mode unless regime switch is explicit
- avoid cash opens, news spikes, and violent price discovery windows

Main failure mode:

- fading a real trend day instead of a failed break

## Lower-priority candidates for later

- mean reversion scalp as a primary v1 family
- grid logic
- martingale
- highly discretionary pattern stacks
- multi-strategy ensemble from day one

## Recommended v1 order

1. `Session Breakout`
2. `Trend Pullback Continuation`
3. `Volatility Contraction Expansion`
4. `Failed Breakout / Range Reversion`

## Practical note

The winning family should not be chosen only by backtest profit.

It should also survive:

- cost stress
- broker execution variance
- walk-forward validation
- demo forward execution

## Extra caution

- On OTC FX in MT5, `iVolume()` is tick volume, not centralized exchange volume. Volume-style filters should not be trusted blindly across brokers.
- For gold and U.S.-sensitive index CFDs, major U.S. data and FOMC windows should be treated as core blackout events unless the strategy is explicitly designed for announcement trading.
