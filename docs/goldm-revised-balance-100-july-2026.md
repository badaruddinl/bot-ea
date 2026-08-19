# GOLDM_REVISED 0.6.0 — USD 100 fixed-lot simulation

## Scope

- Broker data and symbol: local MT5 `GOLD.i#`
- Period: 2026-07-01 through the latest available candle before 2026-08-20
- Starting balance: USD 100
- Scenarios: fixed 0.20 lot and fixed 0.02 lot
- Trades: 16 BUY CORE outcomes from the frozen REVISED 0.6 replay
- Contract size: 100 troy ounces
- Leverage: 1:1000
- Broker margin call / stop-out: 50% / 20%

No order was sent. MT5 `order_calc_margin` and `order_calc_profit` were used for
each historical entry/exit. Commission, swap, execution slippage, and any
spread difference between replay OHLC and executable bid/ask are not included.

## Result

| Metric | 0.20 lot | 0.02 lot |
|---|---:|---:|
| Completed trades | 16 / 16 | 16 / 16 |
| Ending balance | $789.80 | $168.98 |
| Net profit | $689.80 | $68.98 |
| Return | 689.80% | 68.98% |
| Peak balance | $865.00 | $176.50 |
| Max drawdown | $120.40 | $12.04 |
| Max drawdown / peak | 13.92% | 6.82% |
| Maximum required margin | $88.43 | $8.84 |
| Minimum margin level | 119.43% | 1194.74% |
| Profit factor | 3.03 | 3.03 |
| Margin/stop-out failure | none | none |

## Interpretation

The 0.20-lot scenario does not fail in this exact historical sequence because
the first trade is profitable and creates a balance cushion. It nevertheless
uses up to 88.43% of the initial balance as margin and is highly sequence
sensitive. A different first-trade ordering or realistic transaction costs can
materially change survivability.

The 0.02-lot scenario is substantially safer in margin and drawdown terms. The
result is a cash conversion of a signal replay, not an MT5 Strategy Tester EA
report and not evidence of guaranteed executable profit.
