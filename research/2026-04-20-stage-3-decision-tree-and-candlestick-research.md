# Stage 3 Research: Decision Tree and Candlestick Relevance

Date: 2026-04-20  
Goal: convert the prior research into practical decision logic candidates and determine whether candlestick patterns are appropriate for this MT5 bot.

## 1. Executive conclusion

The strongest direction after stage 3 is:

- build the bot around `decision trees and guardrails`, not around a large library of patterns
- use `session`, `news`, `spread`, `ATR`, and `execution feasibility` as first-class gates
- treat candlestick patterns as:
  - sometimes useful as `secondary context`
  - rarely strong enough as `standalone primary alpha`
  - dangerous when multiplied into many tuned thresholds

Practical rule:

- `context first, pattern second`

## 2. Decision-tree direction for the bot

The most realistic strategy families remain:

1. `Session Breakout`
2. `Pullback Continuation`
3. `Volatility Contraction -> Expansion`
4. `Failed Breakout / Range Reversion` as a secondary family

### Why these families remain preferred

Facts:

- BIS and NBER research support the idea that FX activity and volatility cluster around major session overlaps, especially London/New York.  
  Source: <https://www.bis.org/publ/work1094.pdf>  
  Source: <https://www.nber.org/papers/w12413>
- MT5 can expose quote and trade sessions per symbol rather than forcing hardcoded session windows.  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfosessionquote>  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade>
- Scheduled macro announcements materially change intraday volatility and can create jumps.  
  Source: <https://www.nber.org/papers/w5783>  
  Source: <https://www.nber.org/papers/w8959>
- Expected volatility and spread are linked; higher volatility tends to widen spreads.  
  Source: <https://www.nber.org/papers/w4737>
- MT5 provides native primitives to encode session and event guardrails:
  - `SymbolInfoSessionQuote`
  - `SymbolInfoSessionTrade`
  - economic calendar functions
  - `SymbolInfoInteger(...SYMBOL_SPREAD)`
  - `SYMBOL_TRADE_STOPS_LEVEL`
  - `SYMBOL_TRADE_FREEZE_LEVEL`
  - `iATR`  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfosessionquote>  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade>  
  Source: <https://www.mql5.com/en/docs/calendar/calendarvaluehistorybyevent>  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfointeger>  
  Source: <https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants>  
  Source: <https://www.mql5.com/en/docs/indicators/iatr>

Inference:

- These families are more defensible because they can be tied to observable market structure, not just chart folklore.
- The bot should prefer `symbol-aware session state + spread state + ATR state + news state + execution state` over fixed-clock assumptions.

## 3. Candlestick patterns: what the research suggests

### 3.1 What the literature supports

Facts:

- Lo, Mamaysky, and Wang's `Foundations of Technical Analysis` gave evidence that some shape-based technical patterns may show statistical regularities, but the broader implication is nuanced rather than blanket validation of trader folklore.  
  Source: <https://web.mit.edu/people/wangj/pap/LoMamayskyWang00.pdf>
- Marshall, Young, and Rose found that candlestick technical analysis was not profitable in the U.S. equity market sample they studied, which is a strong caution against assuming standalone profitability.  
  Source: <https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID1083064_code114671.pdf?abstractid=980583&mirid=1>
- More recent research on candlestick-image or candlestick-only models often struggles to show that candlestick shapes alone add much predictive power.  
  Source: <https://arxiv.org/abs/2501.12239>
- Overfitting and multiple testing are major concerns for technical rules in finance generally.  
  Source: <https://ssrn.com/abstract=2326253>  
  Source: <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>  
  Source: <https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html>

Inference:

- The evidence does not support using a large library of candlestick patterns as the bot's main signal engine.
- Whatever weak edge exists is highly conditional on market, timeframe, exit rule, and cost model.
- Candlestick evidence is materially less convincing for intraday futures-style use than for some narrow daily-equity studies.

### 3.2 Why candlestick patterns are risky for systematic use

Practical research reasons:

- pattern definitions are often fuzzy
- many patterns are just renamed bar relationships
- multiple-testing risk explodes when trying many candle variants
- after spreads, slippage, and execution delay, weak short-horizon edges often disappear
- the same pattern can mean different things under different session/volatility regimes

### 3.3 Where candlestick patterns can still help

Candlestick/bar-structure logic can still be useful when reduced to objective, limited roles such as:

- `confirmation`
  - e.g. breakout bar closes beyond a range with sufficient body fraction
- `rejection context`
  - e.g. failed breakout closes back inside the range
- `compression context`
  - e.g. inside-bar clusters before expansion
- `stop placement logic`
  - e.g. invalidate beyond the high/low of the structure that triggered the trade
- `execution context`
  - e.g. avoid entering during obvious indecision or low-quality follow-through even when the broader setup is valid

This is materially different from saying:

- hammer = buy
- engulfing = buy
- doji = reversal

Those standalone mappings are not a strong enough foundation for the bot.

## 4. MT5 implementation relevance of candlestick logic

Facts:

- `CopyRates()` and Python `copy_rates_from()` expose OHLCV bar data directly.  
  Source: <https://www.mql5.com/en/docs/series/copyrates>  
  Source: <https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py>
- `MqlRates` packs time, open, high, low, close, tick volume, spread, and real volume into one structure.  
  Source: <https://www.mql5.com/en/docs/constants/structures/mqlrates>
- `iOpen`, `iHigh`, `iLow`, `iClose` return bar values by shift, but each call requests the timeseries and is not locally cached in the same way a copied rates array can be handled.  
  Source: <https://www.mql5.com/en/docs/series/iclose>
- `iBarShift()` maps time to bar index and can return nearest prior bar when exact match is not found.  
  Source: <https://www.mql5.com/en/docs/series/ibarshift>
- In MT5 timeseries, `shift 0` is the newest bar and may still be uncompleted.  
  Source: <https://www.mql5.com/en/docs/series/bufferdirection>  
  Source: <https://www.mql5.com/en/docs/series/copyrates>
- `SeriesInfoInteger(..., SERIES_SYNCHRONIZED)` can be used to confirm data readiness.  
  Source: <https://www.mql5.com/en/docs/series/SeriesInfoInteger>
- `OnTick()` is not a guaranteed handler for every arriving tick because the event queue can coalesce `NewTick` events while one is already queued or running.  
  Source: <https://www.mql5.com/en/docs/event_handlers/ontick>  
  Source: <https://www.mql5.com/en/docs/series/copyticks>
- In MT5 Strategy Tester:
  - spread is treated as floating from historical data
  - real ticks allow intraminute spread movement
  - execution uses Bid/Ask even if bars are built differently
  - `1 Minute OHLC` can create overly deterministic intrabar paths
  - `Open prices only` is only suitable for strategies that decide on new-bar open and do not depend on intrabar sequencing  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/testing_features>  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation>  
  Source: <https://www.mql5.com/en/docs/runtime/testing>
- `iVolume()` in MT5 represents tick volume, not guaranteed centralized real volume for OTC FX.  
  Source: <https://www.mql5.com/en/docs/series/ivolume>

Inference:

- If candle logic is used, it should be encoded via explicit bar relationships from `MqlRates` arrays or copied rates, not through discretionary names first.
- `closed-bar logic` is much safer and more portable than `forming-bar` or intrabar candle logic.
- For intraday and scalping logic, bar-only testing is not enough; real tick validation remains necessary.
- `CopyRates` plus `MqlRates[]` should be preferred over repeated `iOpen/iHigh/iLow/iClose` calls when scanning several bars or several fields.

## 5. Recommended role of candlestick patterns in this project

### Primary recommendation

Do **not** use candlestick patterns as the primary signal family for v1.

### Recommended use

Use bar-structure rules only as one of these:

1. `entry confirmation`
2. `breakout quality check`
3. `failed-breakout detection`
4. `structure-based stop placement`
5. `compression structure detection`
6. `execution timing refinement`

### Not recommended

- huge library of named Japanese candlestick patterns
- one-pattern-one-trade mapping
- parameterizing dozens of candle thresholds per symbol
- volume-based candle logic on OTC FX without broker-specific validation
- intrabar pattern logic that is only validated in `Open prices only`

## 6. Design implication for stage 4 build

The bot should move toward:

- strategy decision tree first
- guard layer second
- optional bar-structure confirmation third
- execution/testing fidelity rules alongside signal rules

So the implementation order should be:

1. session/news/spread/ATR/risk guards
2. family selection logic
3. objective bar-structure confirmation
4. execution and tester-mode constraints

## 7. Implementation notes to carry into build

- Treat `shift 0` as forming unless the logic is explicitly designed to be intrabar.
- Default v1 candle logic to `closed-bar only`, evaluated when a new bar is detected and using `shift 1+`.
- Use symbol-aware session windows from MT5 rather than hardcoded London/New York clocks whenever possible.
- For multi-timeframe logic, do not read higher-timeframe `shift 0` as confirmed structure.
- For multi-symbol logic, do not assume bars open simultaneously across symbols in the tester.
- Require final validation in `Every tick` or `real ticks` for any signal that depends on breakout quality, rejection, stop behavior, or spread-sensitive execution.

## 8. Source list

- <https://www.bis.org/publ/work1094.pdf>
- <https://www.nber.org/papers/w12413>
- <https://www.nber.org/papers/w5783>
- <https://www.nber.org/papers/w8959>
- <https://www.nber.org/papers/w4737>
- <https://www.mql5.com/en/docs/marketinformation/symbolinfosessionquote>
- <https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade>
- <https://www.mql5.com/en/docs/calendar/calendarvaluehistorybyevent>
- <https://www.mql5.com/en/docs/marketinformation/symbolinfointeger>
- <https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants>
- <https://www.mql5.com/en/docs/indicators/iatr>
- <https://www.mql5.com/en/docs/series/ivolume>
- <https://web.mit.edu/people/wangj/pap/LoMamayskyWang00.pdf>
- <https://papers.ssrn.com/sol3/Delivery.cfm/SSRN_ID1083064_code114671.pdf?abstractid=980583&mirid=1>
- <https://arxiv.org/abs/2501.12239>
- <https://ssrn.com/abstract=2326253>
- <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>
- <https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html>
- <https://www.mql5.com/en/docs/series/copyrates>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py>
- <https://www.mql5.com/en/docs/constants/structures/mqlrates>
- <https://www.mql5.com/en/docs/series/iclose>
- <https://www.mql5.com/en/docs/series/ibarshift>
- <https://www.mql5.com/en/docs/series/bufferdirection>
- <https://www.mql5.com/en/docs/series/SeriesInfoInteger>
- <https://www.mql5.com/en/docs/event_handlers/ontick>
- <https://www.mql5.com/en/docs/series/copyticks>
- <https://www.metatrader5.com/en/terminal/help/algotrading/testing_features>
- <https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation>
- <https://www.mql5.com/en/docs/runtime/testing>
