# MT5 Bot Research

Date: 2026-04-20  
Scope: platform capability, strategy constraints, risk engine foundations, and tuning implications for an autonomous EA/bot

## 1. Research summary

The build should start from `MT5`, not `MT4`.

Why:

- Official `MQL5` exposes account, symbol, margin, profit, order-check, and economic-calendar functions directly.
- Official `MetaTrader5` Python integration exposes connection, account info, symbol info, ticks/rates, order calculation, order check, and order send from a running MT5 terminal.
- For a bot that must adapt to `equity`, `symbol characteristics`, and `market conditions`, MT5 gives a cleaner foundation for both native and hybrid architectures.

Core design conclusion:

- Use research to create a `baseline trading/risk framework`.
- Use live terminal/account data to `specialize` it.
- Use backtest plus demo forward test to `tune` it.
- Do not let internet research alone decide production parameters.

## 2. Platform facts from official MetaTrader sources

### 2.1 Python bridge to MT5

Facts:

- The official Python integration lists `initialize`, `login`, `shutdown`, `account_info`, `terminal_info`, `symbols_get`, `symbol_info`, `symbol_info_tick`, `copy_rates_*`, `copy_ticks_*`, `order_calc_margin`, `order_calc_profit`, `order_check`, `order_send`, `positions_get`, and history functions.  
  Source: <https://www.mql5.com/en/docs/python_metatrader5>
- The Python package communicates directly with the running MT5 terminal and is intended for data access plus statistical/ML work.  
  Source: <https://www.mql5.com/en/docs/python_metatrader5>
- Official MetaQuotes AlgoBook notes that native Python support does not provide event handlers such as `OnTick`, `OnBookEvent`, or `OnTradeTransaction`; Python logic needs its own polling or scheduling loop.  
  Source: <https://www.mql5.com/en/book/advanced/python>
- MetaQuotes AlgoBook also positions Python integration as a data-processing and external-analysis layer rather than a full event-native replacement for MQL5 execution logic.  
  Source: <https://www.mql5.com/en/book/advanced/python>

Implication:

- A host PC or VPS must keep `MT5` running if the bot uses the Python bridge.
- Python is excellent for orchestration, analytics, research, tuning, and hybrid decision logic.
- Execution-critical logic can still stay in native `MQL5` if lower complexity and lower dependency count are preferred.
- A hybrid design should normally keep `MQL5` as the event-sensitive execution layer and use `Python` as the supervisory, analytics, or model-inference layer.

### 2.2 Account, symbol, and market data access

Facts:

- `AccountInfoDouble()` exposes key account values including `ACCOUNT_BALANCE`, `ACCOUNT_EQUITY`, `ACCOUNT_MARGIN`, `ACCOUNT_MARGIN_FREE`, `ACCOUNT_MARGIN_LEVEL`, and stop-out fields.  
  Source: <https://www.mql5.com/en/docs/account/accountinfodouble>
- `SymbolInfoDouble()` exposes symbol properties, while MetaQuotes recommends `SymbolInfoTick()` for last-tick data.  
  Source: <https://www.mql5.com/en/docs/marketinformation/symbolinfodouble>
- Python `symbol_info()` returns symbol properties in one call, including fields such as `spread`, `digits`, `trade_stops_level`, `volume_min`, `volume_max`, `volume_step`, and `trade_contract_size`.  
  Source: <https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py>

Implication:

- The bot can inspect the account and symbol before every decision.
- This is enough to build symbol-aware lot sizing, spread filters, minimum-stop checks, and equity-aware risk reduction.

### 2.3 Profit, margin, and pre-trade validation

Facts:

- `OrderCalcProfit()` calculates projected profit in account currency for a planned trade.  
  Source: <https://www.mql5.com/en/docs/trading/ordercalcprofit>
- `OrderCalcMargin()` calculates required margin in account currency for a planned order.  
  Source: <https://www.mql5.com/en/docs/trading/OrderCalcMargin>
- `OrderCheck()` returns a trade-check result structure and is the correct pre-send validation gate for funds sufficiency and request validity.  
  Source: <https://www.mql5.com/en/docs/trading/ordercheck>
- In Python, `order_check()` returns the `MqlTradeCheckResult` analogue and `order_send()` sends the trade request.  
  Source: <https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py>  
  Source: <https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py>
- Successful request submission is not the same thing as successful execution; server return codes and result details must still be checked.  
  Source: <https://www.mql5.com/en/docs/trading/ordersend>  
  Source: <https://www.mql5.com/en/docs/standardlibrary/tradeclasses/ctrade/ctradesell>

Implication:

- Lot sizing should not be hardcoded from generic pip formulas when the platform can price the trade in account currency directly.
- The bot should use a staged gate:
  1. symbol validation
  2. `OrderCalcProfit`
  3. `OrderCalcMargin`
  4. `OrderCheck`
  5. `OrderSend`
  6. post-send retcode verification

### 2.4 Economic calendar and news filtering

Facts:

- MT5 provides official economic-calendar functions that support automated analysis by country, currency, and importance.  
  Source: <https://www.mql5.com/en/docs/calendar>
- The calendar functions use trade-server time, not local PC time.  
  Source: <https://www.mql5.com/en/docs/calendar>

Implication:

- News filters can be native to the EA design.
- Time normalization must be done against server time, not only local time.
- Because economic-calendar support is officially documented on the native MQL5 side and not listed in the official Python function set, the safest default is to keep news filtering in native MQL5.

## 3. Trading and risk findings from external research

### 3.1 Position sizing and margin discipline

Facts:

- CME states that contract choice, position size, and stop placement are core risk variables, and that some markets have larger tick values and larger dollar swings than others.  
  Source: <https://www.cmegroup.com/education/courses/things-to-know-before-trading-cme-futures/position-and-risk-management>
- CME also notes that margin requirements are a control layer, not a target operating zone.  
  Source: <https://www.cmegroup.com/education/courses/things-to-know-before-trading-cme-futures/position-and-risk-management>
- OANDA states that limiting trade size and using stop losses helps maintain sufficient margin, and explicitly warns against leveraging the entire account balance.  
  Source: <https://www.oanda.com/us-en/learn/introduction-to-leverage-trading/what-is-margin-in-trading/>

Inference:

- The bot should treat `margin availability` as a hard gate and `ample free margin` as a design target.
- Small-equity accounts should use far stricter size and exposure limits than broker minimums.

### 3.2 Slippage, gaps, and stop behavior

Facts:

- IG defines slippage as execution at a different price than requested and cites two main drivers: high volatility and gapping.  
  Source: <https://www.ig.com/en/glossary-trading-terms/slippage-definition>
- IG also notes that regular stop-loss and trailing-stop behavior does not protect against slippage if the market gaps.  
  Source: <https://www.ig.com/en-ch/risk-management>

Inference:

- The bot must price in `spread + slippage allowance`, especially for scalping.
- News periods, session opens, and low-liquidity windows need special treatment or full avoidance.

### 3.3 Scalping timing and liquidity

Facts:

- Babypips describes the `London-New York overlap` as the most active forex period, with high liquidity, tighter spreads, and increased volatility.  
  Source: <https://www.babypips.com/learn/forex/session-overlaps>
- IG notes that scalping works best when liquidity and volatility are sufficient, and also warns that high volatility increases risk.  
  Source: <https://www.ig.com/en/trading-strategies/a-beginners--guide-to-a-forex-scalping-strategy-210304>

Inference:

- A forex scalping baseline should be session-aware and prefer high-liquidity windows.
- For index/gold CFDs, session and broker-specific friction matter even more; the baseline must be validated on the actual broker symbol list.

### 3.4 Risk-reward framing

Facts:

- IG defines risk-reward as expected reward relative to the amount risked and emphasizes that higher risk does not imply better outcomes, only greater exposure.  
  Source: <https://www.ig.com/en/risk-management/risk-reward>

Inference:

- The bot should not chase frequency or aggression at the expense of expectancy.
- Strict mode for small accounts should require stronger confluence and/or better projected trade quality before entry.

## 4. Additional microstructure note from broader research

The primary scope of this repository is still `MT5 forex/index/gold style automation`, but one research pass also reviewed U.S. equity intraday sources. The market is different, yet the execution lessons still transfer.

Facts:

- SEC/Investor.gov explains that market orders are not price guarantees, limit orders can miss fills, and stop orders can execute far from the trigger in fast markets because they become market orders once activated.  
  Source: <https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-14>
- SEC also explains that after-hours trading typically has lower liquidity, wider spreads, and higher price uncertainty than regular core sessions.  
  Source: <https://www.sec.gov/files/afterhourtrading.pdf>

Inference:

- Even outside U.S. equities, the same design lesson applies to MT5 automation: avoid low-liquidity windows in v1 and never assume stops will fill perfectly under stress.

## 5. What this means for the bot

### 4.1 Architecture recommendation

Primary recommendation:

- `MT5 first`, with a design that supports both:
  - `native MQL5 EA`
  - `hybrid MT5 + Python`

Suggested split:

- `MQL5 EA`: execution, symbol validation, risk gate, position management, calendar filter, logging
- `Python`: research, backtest orchestration, optimization, analytics, parameter adaptation, optional higher-level decision module

Reason:

- This preserves reliability in execution while leaving room for richer adaptation later.

### 4.2 Strategy families worth testing first

These are design recommendations, not verified alpha:

1. `Session breakout scalp`
- Best first candidate for automation because it is rules-based.
- Needs range definition, spread cap, minimum volatility, and news filter.

2. `Trend pullback scalp`
- Good for liquid major FX pairs or select indices.
- Needs trend filter plus fast invalidation.

3. `Intraday continuation`
- Lower trade frequency and usually more forgiving than ultra-fast scalping.
- Better candidate if equity is limited and friction is high.

Lowest priority at the start:

- mean reversion on symbols with unstable spreads
- martingale/grid logic
- multi-symbol aggressive scalping on small equity

## 6. Risk engine recommendations

### 5.1 Core sizing

Recommended formula:

```text
equity = current account equity
risk_cash = equity * risk_pct
sl_cash_1lot = abs(OrderCalcProfit(side, symbol, 1.0, entry_price, stop_price))
size_raw = risk_cash / sl_cash_1lot
size_step_aligned = floor_to_volume_step(size_raw)
```

Then apply:

- spread allowance
- slippage allowance
- commission allowance if applicable
- symbol min/max/step normalization

### 5.2 Multi-stage gating

Recommended gates:

1. `Symbol gate`
- visible/selectable
- spread under threshold
- stop distance valid
- market session active
- latest tick not stale

2. `Risk gate`
- risk per trade within account policy
- total open risk within cap
- correlation cluster cap not exceeded

3. `Margin gate`
- estimated margin acceptable
- post-check free margin safe
- post-check margin level well above broker stress zone

4. `Execution gate`
- acceptable deviation
- allowed fill mode
- no repeated trade-server rejection pattern

### 5.3 Equity-aware strict mode

If the user has limited equity but still wants a heavy instrument, the bot should not simply comply. It should:

- warn that the symbol is risky for the account size
- automatically reduce risk per trade
- cut maximum simultaneous positions
- widen margin buffer requirements
- require stronger setup quality
- reduce daily trade count
- block trading near major news and abnormal spreads

Practical policy suggestion:

- `Normal mode`: standard guardrails
- `Caution mode`: reduced size, fewer entries
- `Strict mode`: very low risk, high selectivity, hard stop after drawdown or friction anomalies

## 7. Instrument suitability model

Instrument suitability should be determined dynamically from account size and symbol properties, not from name alone.

Recommended scoring dimensions:

```text
margin_footprint = margin_for_min_trade / equity
risk_footprint   = worst_case_SL_loss_for_min_trade / equity
friction_ratio   = spread_cash / planned_risk_cash
```

Suggested interpretation:

- `Light`
  - margin footprint small
  - minimum lot allows fine sizing
  - spread friction low
- `Medium`
  - acceptable but should trade smaller or more selectively
- `Heavy`
  - minimum lot is too coarse for the account
  - spread friction is large relative to planned risk
  - margin footprint is too large

Heavy instruments for small equity should trigger:

- recommendation against trading
- automatic downgrade to strict mode if the user insists

## 8. Parameters: what should come from the user vs the system

### 7.1 User-supplied

- market style: `scalping`, `intraday`, `swing`
- allowed asset class: `forex`, `index`, `gold`, or custom allowlist
- risk profile: `conservative`, `normal`, `aggressive`
- account mode: `demo` or `live`
- optional hard boundaries:
  - max daily loss
  - max positions
  - session preference

### 7.2 Auto-read from MT5

- equity and free margin
- symbol list and symbol properties
- spread and tick data
- trading session availability
- stop-level constraints
- current positions and total exposure

### 7.3 Tuned/optimized

- stop-loss multiplier or range
- take-profit target logic
- volatility filter thresholds
- spread cap by session
- cooldown length
- session enablement
- quality threshold for entry

## 9. Tuning implications

The bot can be tuned from research-informed priors, but not finalized from research alone.

Proper tuning flow:

1. Define baseline per strategy family.
2. Pull historical data from MT5.
3. Backtest on broker-specific symbols.
4. Run walk-forward or rolling validation.
5. Demo forward test.
6. Only then choose live defaults.

What not to do:

- optimize on a single period only
- fit one symbol and assume transferability
- assume internet examples map cleanly to the user's broker
- ignore spread/slippage degradation in forward conditions

## 10. First build recommendation

Best first build:

- `MT5-based bot`
- single symbol
- single strategy family
- strong risk engine
- complete logging
- demo-only first

Priority order:

1. symbol and account introspection
2. risk engine
3. execution engine
4. baseline strategy
5. logging and telemetry
6. tuning pipeline

## 11. Source list

Official/primary:

- <https://www.mql5.com/en/docs/python_metatrader5>
- <https://www.mql5.com/en/book/advanced/python>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5ordercheck_py>
- <https://www.mql5.com/en/docs/python_metatrader5/mt5ordersend_py>
- <https://www.mql5.com/en/docs/account/accountinfodouble>
- <https://www.mql5.com/en/docs/marketinformation/symbolinfodouble>
- <https://www.mql5.com/en/docs/trading/ordercalcprofit>
- <https://www.mql5.com/en/docs/trading/OrderCalcMargin>
- <https://www.mql5.com/en/docs/trading/ordercheck>
- <https://www.mql5.com/en/docs/trading/ordersend>
- <https://www.mql5.com/en/docs/calendar>

Supplementary education:

- <https://www.cmegroup.com/education/courses/things-to-know-before-trading-cme-futures/position-and-risk-management>
- <https://www.oanda.com/us-en/learn/introduction-to-leverage-trading/what-is-margin-in-trading/>
- <https://www.ig.com/en/glossary-trading-terms/slippage-definition>
- <https://www.ig.com/en-ch/risk-management>
- <https://www.ig.com/en/trading-strategies/a-beginners--guide-to-a-forex-scalping-strategy-210304>
- <https://www.babypips.com/learn/forex/session-overlaps>
- <https://www.ig.com/en/risk-management/risk-reward>
- <https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-14>
- <https://www.sec.gov/files/afterhourtrading.pdf>
