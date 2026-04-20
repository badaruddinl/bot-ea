# Stage 2 Deep Research

Date: 2026-04-20  
Goal: deepen the project beyond baseline MT5 capability into execution variance, validation robustness, parameter governance, and practical strategy families for future testing.

## 1. Core conclusion

The strongest design direction after stage 2 research is:

- `MT5 first`
- `fixed alpha, adaptive risk`
- `broker-derived execution constraints`
- `hard validation protocol before any live deployment`

This means:

- the bot should not rely on one broker behaving like another
- the bot should not expose many user knobs
- the bot should not trust a single backtest split
- the bot should not optimize entry logic aggressively

## 2. Broker execution variance

### Facts

- MT5 exposes execution and broker constraints per symbol, including `SYMBOL_TRADE_EXEMODE`, `SYMBOL_FILLING_MODE`, `SYMBOL_TRADE_STOPS_LEVEL`, `SYMBOL_TRADE_FREEZE_LEVEL`, `SYMBOL_TRADE_MODE`, symbol sessions, and volume constraints.  
  Source: <https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants>
- `OrderSend()==true` does not guarantee final execution success; the final status still depends on returned trade result codes and possibly multiple downstream trade events.  
  Source: <https://www.mql5.com/en/docs/trading/ordersend>
- `OnTradeTransaction()` can emit multiple events for one request, and the arrival order is not guaranteed.  
  Source: <https://www.mql5.com/en/docs/event_handlers/ontradetransaction>
- `SymbolInfoTick()` is the preferred call for fresh bid/ask/last tick data.  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfotick>
- `SymbolSelect()` and `SymbolIsSynchronized()` matter operationally for symbols that may not yet be active or fully synchronized.  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolselect>  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolissynchronized>
- VPS behavior has real limitations: no DLLs, scripts do not migrate, non-standard charts are not migrated, and migration state matters.  
  Source: <https://www.metatrader5.com/en/terminal/help/virtual_hosting/virtual_hosting_migration>

### Design implication

The bot needs an `execution guard layer` that:

- reads broker/symbol capabilities at runtime
- validates all prices against stop/freeze levels
- selects filling policy from what the symbol allows
- assumes partial fills and delayed downstream events are normal
- handles reconnect, stale ticks, and server-side rejection as standard conditions

## 3. Validation robustness and anti-overfitting

### Facts

- MetaTrader 5 Strategy Tester supports:
  - forward testing
  - custom commissions and margin rules
  - execution delay
  - real tick testing
  - multi-currency testing  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/testing>  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/strategy_optimization>  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation>
- MT5 forward testing is a split of the total period into backtest and later forward segment; it is not a full rolling walk-forward engine.  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/testing>
- In Strategy Tester:
  - spread is treated as floating and taken from historical data
  - real ticks allow intraminute spread movement
  - generated ticks within a minute use fixed spread for that minute  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/testing_features>  
  Source: <https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation>
- Literature on overfitting and multiple testing is strongly cautionary:
  - White's Reality Check
  - Probability of Backtest Overfitting
  - Deflated Sharpe Ratio  
  Source: <https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html>  
  Source: <https://ssrn.com/abstract=2326253>  
  Source: <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>
- CFA and related validation literature emphasize time-ordered splits, blocked gaps, realistic implementation timing, and regime awareness.  
  Source: <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation>  
  Source: <https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/rf-brief/investment-model-validation.pdf>

### Design implication

The project should use a strict research cycle:

1. define hypothesis before tuning
2. split data chronologically
3. optimize on development only
4. validate with MT5 forward split
5. repeat in rolling walk-forward windows
6. stress test costs and delays
7. keep final untouched holdout
8. demo forward test on target broker

## 4. Parameter governance

### Facts

- MT5 exposes account constraints such as leverage, margin mode, FIFO close, hedge allowance, stop-out settings, and account trade permission.  
  Source: <https://www.mql5.com/en/docs/constants/environment_state/accountinformation>
- MT5 exposes symbol-side execution and sizing constraints including volume min/max/step, tick value, contract size, stop distance, freeze distance, filling mode, order mode, and session timing.  
  Source: <https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants>
- `OrderCheck`, `OrderCalcMargin`, and `SymbolInfoMarginRate` allow feasibility/risk checks to be grounded in live broker/account state.  
  Source: <https://www.mql5.com/en/docs/trading/ordercheck>  
  Source: <https://www.mql5.com/en/docs/trading/OrderCalcMargin>  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfomarginrate>
- Risk and portfolio literature favors more stable risk budgeting over fragile return estimation.  
  Source: <https://www.nber.org/papers/w0444>  
  Source: <https://www.nber.org/papers/w22208>  
  Source: <https://mpra.ub.uni-muenchen.de/37749/2/MPRA_paper_37749.pdf>

### Design implication

The cleanest parameter governance is:

- `broker-derived`
  - all execution constraints
  - margin and symbol metadata
  - live spread/liquidity state
- `user-supplied`
  - symbol allowlist
  - risk profile
  - daily loss cap
  - gross exposure cap
  - session permissions
- `fixed`
  - strategy family
  - feature set
  - volatility estimator form
  - sizing formula
  - drawdown throttle curve
- `adaptive`
  - size scale
  - spread/slippage gates
  - margin headroom throttle
  - drawdown throttling
  - stop distance as volatility-normalized risk control

The anti-overfit principle is:

- adapt `scale`, not `logic`

## 5. Candidate strategy families to test first

These are not claims of profitability. They are candidates because they are more rule-based and easier to govern safely.

### 5.1 Session breakout

Useful when:

- liquidity and volatility both increase around a known session handoff
- the symbol reacts cleanly to session range breaks

Supportive facts:

- London-New York overlap is one of the most active forex windows, with high liquidity and tighter spreads.  
  Source: <https://www.babypips.com/learn/forex/session-overlaps>
- OANDA session research also points to concentrated activity around high-volume windows.  
  Source: <https://www.oanda.com/us-en/trade-tap-blog/asset-classes/forex/best-time-to-trade-forex-volume-insights/>
- Breakout trading is closely tied to volatility and confirmation to avoid false breaks.  
  Source: <https://www.ig.com/en/trading-strategies/what-is-a-breakout-trading-strategy-and-how-do-you-trade-with-it-230619>

Guardrails:

- require spread cap
- require breakout confirmation
- block around major news
- avoid if symbol has frequent fake-outs in low-liquidity hours

### 5.2 Trend pullback continuation

Useful when:

- a clean intraday trend exists
- the market pulls back temporarily without clear reversal structure

Supportive facts:

- Pullbacks are temporary pauses within broader trends and should not be assumed safe without risk control.  
  Source: <https://www.ig.com/en/glossary-trading-terms/pullback-definition>
- Continuation structures are often traded by waiting for breakout in the direction of the prevailing trend.  
  Source: <https://www.babypips.com/forexpedia/continuation-pattern>

Guardrails:

- require trend filter first
- require volatility not too low and not chaotic
- do not use on highly choppy/noise-dominant sessions

### 5.3 Volatility contraction then expansion

Useful when:

- the symbol compresses before directional release
- a breakout from low realized volatility can be captured with tight invalidation

Supportive facts:

- IG and general educational material consistently tie breakout opportunity to volatility transitions, but also warn that false breaks and cost friction matter.  
  Source: <https://www.ig.com/en/trading-strategies/what-is-a-breakout-trading-strategy-and-how-do-you-trade-with-it-230619>

Guardrails:

- require minimum post-breakout follow-through
- reject if spread consumes too much of expected move
- reject around scheduled macro events unless explicitly testing a news-driven design

### 5.4 Intraday continuation over pure mean reversion for v1

Research implication:

- continuation/breakout logic is usually easier to formalize and protect with rules than mean-reversion scalp logic under retail spread/slippage constraints
- mean reversion can still be researched later, but it is more sensitive to false entries when trend days emerge

## 6. Markets and time windows

Practical research implication:

- avoid weekend boundary conditions and low-liquidity edges
- avoid Friday close widening when possible
- avoid pre-news and just-after-news periods unless the strategy is designed for them

Supportive facts:

- OANDA notes spread widening into low-liquidity periods and weekend transitions.  
  Source: <https://www.oanda.com/assets/documents/252/Hours_of_Operation.pdf>
- IG and OANDA educational material both emphasize that liquidity and volatility should be balanced; high volatility without liquidity quality is dangerous for short-term execution.  
  Source: <https://www.ig.com/en/trading-strategies/a-beginners--guide-to-a-forex-scalping-strategy-210304>  
  Source: <https://www.oanda.com/us-en/trade-tap-blog/asset-classes/forex/forex-volatility--understanding-analyzing-trading-currency-fluctuations/>

## 7. Decision impact on the project

After stage 2, the most defensible v1 path is:

- one broker
- one to three carefully chosen symbols
- one strategy family
- hard execution guard layer
- hard validation protocol
- no live deployment before demo validation

## 8. Source list

- <https://www.mql5.com/en/docs/constants/environment_state/marketinfoconstants>
- <https://www.mql5.com/en/docs/trading/ordersend>
- <https://www.mql5.com/en/docs/event_handlers/ontradetransaction>
- <https://www.mql5.com/en/docs/marketinformation/symbolinfotick>
- <https://www.mql5.com/en/docs/marketinformation/symbolselect>
- <https://www.mql5.com/en/docs/marketinformation/symbolissynchronized>
- <https://www.metatrader5.com/en/terminal/help/virtual_hosting/virtual_hosting_migration>
- <https://www.metatrader5.com/en/terminal/help/algotrading/testing>
- <https://www.metatrader5.com/en/terminal/help/algotrading/strategy_optimization>
- <https://www.metatrader5.com/en/terminal/help/algotrading/testing_features>
- <https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation>
- <https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html>
- <https://ssrn.com/abstract=2326253>
- <https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf>
- <https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/backtesting-and-simulation>
- <https://rpc.cfainstitute.org/sites/default/files/-/media/documents/article/rf-brief/investment-model-validation.pdf>
- <https://www.nber.org/papers/w0444>
- <https://www.nber.org/papers/w22208>
- <https://mpra.ub.uni-muenchen.de/37749/2/MPRA_paper_37749.pdf>
- <https://www.babypips.com/learn/forex/session-overlaps>
- <https://www.oanda.com/us-en/trade-tap-blog/asset-classes/forex/best-time-to-trade-forex-volume-insights/>
- <https://www.ig.com/en/trading-strategies/what-is-a-breakout-trading-strategy-and-how-do-you-trade-with-it-230619>
- <https://www.ig.com/en/glossary-trading-terms/pullback-definition>
- <https://www.babypips.com/forexpedia/continuation-pattern>
- <https://www.oanda.com/assets/documents/252/Hours_of_Operation.pdf>
- <https://www.ig.com/en/trading-strategies/a-beginners--guide-to-a-forex-scalping-strategy-210304>
- <https://www.oanda.com/us-en/trade-tap-blog/asset-classes/forex/forex-volatility--understanding-analyzing-trading-currency-fluctuations/>"}}
