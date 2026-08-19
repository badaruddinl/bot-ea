# GOLDM_REVISED 0.6.0 — USD 100, Jan–19 Aug 2026

## Scope

- Broker data: local MT5 `GOLD.i#`, account server `XMGlobal-MT5 5`
- Replay window: 2026-01-01 00:00 through 2026-08-19 09:55, GMT+3
- Last replayed M5 candle was closed; the live 09:55 candle was excluded
- Starting balance: USD 100
- Signal engine: frozen REVISED 0.6 BUY generator
- Normal execution: engine stop and target
- Wide execution: stop distance 2×; target distance is measured from entry to
  the engine's original target
- Lot sizes: 0.20 and 0.02

The wide scenarios replay every M1 candle independently. A later signal is
skipped while the preceding position remains open under that scenario.

## Baseline signal replay

The normal engine produced 87 BUY signals: 42 targets, 44 stops, one ambiguous
same-M1-bar outcome, and no open position at the end of the test. Total result
was `+31.490832R`, expectancy `+0.361964R`, and maximum drawdown
`6.843798R`.

## USD 100 cash results

| Execution | Lot | Completed | Ending balance | Net | Profit factor | Max DD / peak | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| Normal | 0.20 | 1 / 87 | $43.40 | -$56.60 | 0.00 | 56.60% | insufficient margin at next entry |
| Normal | 0.02 | 87 / 87 | $342.38 | +$242.38 | 2.03 | 23.74% | completed |
| Stop 2×, target 1× | 0.20 | 0 / 85 | $17.56 | -$82.44 | — | 82.44% | stop-out in first trade |
| Stop 2×, target 1× | 0.02 | 85 / 85 | $324.26 | +$224.26 | 1.64 | 42.17% | completed |
| Stop 2×, target 2× | 0.20 | 0 / 76 | $17.56 | -$82.44 | — | 82.44% | stop-out in first trade |
| Stop 2×, target 2× | 0.02 | 76 / 76 | $426.04 | +$326.04 | 1.73 | 43.00% | completed |
| Stop 2×, target 2.25× | 0.20 | 0 / 74 | $17.56 | -$82.44 | — | 82.44% | stop-out in first trade |
| Stop 2×, target 2.25× | 0.02 | 74 / 74 | **$500.67** | **+$400.67** | **1.90** | 43.00% | completed |
| Stop 2×, target 2.5× | 0.20 | 0 / 70 | $17.56 | -$82.44 | — | 82.44% | stop-out in first trade |
| Stop 2×, target 2.5× | 0.02 | 70 / 70 | $458.69 | +$358.69 | 1.81 | 43.00% | completed |
| Stop 2×, target 3× | 0.20 | 0 / 67 | $17.56 | -$82.44 | — | 82.44% | stop-out in first trade |
| Stop 2×, target 3× | 0.02 | 67 / 67 | $453.10 | +$353.10 | 1.74 | 43.00% | completed |

For normal 0.20 lot, the first completed stop reduces balance to $43.40. The
next signal on 2026-01-07 03:07 server time needs $89.89 margin and cannot be
opened. With a 2× stop, the first signal on 2026-01-02 14:45 reaches the
broker's simulated 20% stop-out threshold before the widened stop; therefore
changing its target cannot rescue any 0.20-wide scenario.

## Stop-2× target sweep at 0.02 lot

| Target distance | Trades | TP / SL | Skipped | Expectancy | Ending balance | Profit factor | Max DD / peak |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1.00× | 85 | 52 / 33 | 2 | +0.160R | $324.26 | 1.64 | 42.17% |
| 1.25× | 82 | 42 / 40 | 5 | +0.045R | $279.96 | 1.44 | 43.00% |
| 1.50× | 79 | 37 / 42 | 8 | +0.047R | $229.68 | 1.28 | 43.00% |
| 1.75× | 79 | 35 / 44 | 8 | +0.063R | $302.23 | 1.43 | 43.00% |
| 2.00× | 76 | 35 / 41 | 11 | +0.198R | $426.04 | 1.73 | 43.00% |
| 2.10× | 75 | 34 / 41 | 12 | +0.215R | $429.36 | 1.72 | 43.00% |
| 2.15× | 75 | 34 / 41 | 12 | +0.233R | $448.12 | 1.76 | 43.00% |
| 2.20× | 75 | 34 / 41 | 12 | +0.251R | $466.85 | 1.80 | 43.00% |
| 2.25× | 74 | 34 / 40 | 13 | **+0.286R** | **$500.67** | **1.90** | 43.00% |
| 2.30× | 72 | 32 / 40 | 15 | +0.263R | $472.26 | 1.84 | 43.00% |
| 2.35× | 72 | 31 / 41 | 15 | +0.242R | $457.28 | 1.78 | 43.00% |
| 2.40× | 72 | 31 / 41 | 15 | +0.260R | $474.57 | 1.82 | 43.00% |
| 2.50× | 70 | 29 / 41 | 17 | +0.239R | $458.69 | 1.81 | 43.00% |
| 3.00× | 67 | 25 / 42 | 20 | +0.277R | $453.10 | 1.74 | 43.00% |

## Verdict

At USD 100, 0.20 lot is not viable in this replay. The normal 0.02 setup has
the better risk-adjusted profile: higher R expectancy and profit factor than
the widened-stop variants, and materially lower peak-relative drawdown.

Within the stop-2× family, target 2.25× remains the performance winner. It has
the highest ending balance, expectancy, and profit factor in the local
2.00×–2.50× plateau, but its cash drawdown is about 43% and 13 original signals
are skipped due to longer holding periods. It remains a research candidate,
not an engine default, until it passes an untouched forward window.

Cash calculations use MT5 `order_calc_margin` and `order_calc_profit` for the
connected broker contract. Commission, swap, slippage, and executable bid/ask
differences are not included. No order was sent.
