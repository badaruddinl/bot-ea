# Stage 4 Research: Implementation and Live Research Notes

Date: 2026-04-20  
Goal: continue research while implementation scaffolding begins, so design decisions stay aligned with official MT5 constraints and more recent market-structure evidence.

## 1. Executive conclusion

The latest research batch reinforces the current architecture:

- keep `risk and execution constraints` as first-class logic
- keep `session/news/spread/volatility` ahead of pattern logic
- treat candlestick or bar-pattern logic as `secondary context`
- design the first live-capable integration around `symbol capability snapshots` and `server-time normalization`

## 2. Latest MT5 implementation facts

Facts from official MetaQuotes / MQL5 documentation:

- trading and quoting sessions are defined per symbol and per weekday, and a symbol can have multiple sessions in one day  
  Source: <https://www.mql5.com/en/book/automation/symbols/symbols_sessions>  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfosessiontrade>  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfosessionquote>
- execution capability is not captured by sessions alone; the engine also needs trade mode, order mode, execution mode, and filling mode  
  Source: <https://www.mql5.com/en/book/automation/symbols/symbols_trade_mode>  
  Source: <https://www.mql5.com/en/book/automation/symbols/symbols_execution_filling>
- spread, stop distance, and freeze distance are execution-critical and must be validated against current Bid/Ask close to send time  
  Source: <https://www.mql5.com/en/book/automation/symbols/symbols_spreads_levels>
- `OrderCalcMargin` and `OrderCalcProfit` are useful pre-estimators, but `OrderCheck` gives a richer pre-trade projection and still does not guarantee fill  
  Source: <https://www.mql5.com/en/docs/trading/ordercalcmargin>  
  Source: <https://www.mql5.com/en/docs/trading/ordercalcprofit>  
  Source: <https://www.mql5.com/en/docs/trading/ordercheck>
- economic calendar timestamps use `TimeTradeServer`, not local host time  
  Source: <https://www.mql5.com/en/docs/calendar/calendarvaluehistory>  
  Source: <https://www.mql5.com/en/book/advanced/calendar>
- for tester use, calendar data needs explicit cache handling rather than assuming live-online calendar access  
  Source: <https://www.mql5.com/en/book/advanced/calendar/calendar_cache_tester>
- `OnTick` is not a perfect one-event-per-tick stream; heavy per-tick logic can miss granularity because tick events can coalesce while the handler is busy  
  Source: <https://www.mql5.com/en/docs/event_handlers/ontick>
- multi-symbol new-bar timing is not guaranteed to be simultaneous, and test-mode fidelity differs sharply between `Open prices only`, `Every tick`, and `Every tick based on real ticks`  
  Source: <https://www.mql5.com/en/docs/runtime/testing>  
  Source: <https://www.mql5.com/en/book/automation/tester/tester_ticks>  
  Source: <https://www.mql5.com/en/welcome/en-metatrader-5-real-ticks-based-strategy-tester>

Inference:

- the project should maintain a `symbol capability snapshot` and refresh it shortly before execution
- server time should be the canonical clock for sessions and news logic
- the first baseline strategy should stay `closed-bar first`, with final validation on `Every tick` or `real ticks`

## 3. Latest market-structure reinforcement

Facts:

- the BIS 2025 Triennial FX Survey confirms the continued concentration of FX trading in a few major centers, reinforcing why session-aware logic remains structurally important  
  Source: <https://www.bis.org/statistics/rpfx25_fx.pdf>
- broader intraday evidence continues to support session dependence, announcement sensitivity, and volatility clustering in FX  
  Source: <https://www.nber.org/papers/w12413>  
  Source: <https://www.nber.org/papers/w5783>  
  Source: <https://www.nber.org/papers/w8959>
- expected volatility and liquidity stress remain linked to wider spreads and worse execution conditions  
  Source: <https://www.nber.org/papers/w4737>  
  Source: <https://www.bis.org/publ/work836.htm>

Inference:

- the EA should never decide from chart structure alone
- the risk and execution layers need explicit rules for:
  - session activity
  - scheduled news windows
  - spread efficiency
  - volatility regime

## 4. Latest candlestick / bar-pattern conclusion

Facts from the broader research batch:

- simple bar-pattern and candlestick rules often show some statistical predictive content, but economic value is usually weak after costs and multiple-testing correction  
  Source: <https://doi.org/10.2307/3666289>  
  Source: <https://doi.org/10.1016/j.jfineco.2012.06.001>  
  Source: <https://doi.org/10.1016/j.jbankfin.2005.08.001>
- where candlestick rules seem to survive, success is often highly dependent on `holding and exit design`, not just on the pattern label itself  
  Source: <https://doi.org/10.1016/j.jbankfin.2015.09.009>
- intraday futures evidence is especially weak for standalone candlestick rules after realistic evaluation  
  Source: <https://doi.org/10.3905/jod.2005.580514>

Inference:

- candlestick logic should remain a `feature layer`, not the core alpha layer
- the most credible uses remain:
  - breakout quality confirmation
  - failed-breakout confirmation
  - contraction structure detection
  - rejection / exhaustion context
  - stop and invalidation structure

## 5. Impact on the current scaffold

The scaffold that started in `src/bot_ea/` should evolve in this order:

1. `risk_engine`
2. `mt5_adapter`
3. `symbol/account snapshot loaders`
4. `execution_guard`
5. `baseline strategy family`
6. `telemetry and validation harness`

The newest research supports these implementation decisions:

- include session and capability fields in symbol snapshots
- normalize all news/session time logic to server time
- keep the first strategy closed-bar and single-family
- do not invest early effort in a large candlestick dictionary
- design the execution layer to refresh spread, stops, freeze, and order capability right before `OrderSend`

## 6. Immediate build implication

The next coding slice should be:

- implement real MT5-backed account and symbol introspection
- extend the adapter with margin and order-check plumbing
- keep the strategy family thin until execution realism is wired in

This keeps the project aligned with the strongest evidence gathered so far.
