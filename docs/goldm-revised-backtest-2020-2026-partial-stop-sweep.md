# GOLDM_REVISED — 2020–2026 partial stop sweep

## Scope

- Broker data: local MT5 `GOLD.i#`, server `XMGlobal-MT5 5`
- Window: 2020-01-01 00:00 through 2026-08-19 10:45, GMT+3
- Engine: frozen `GOLDM_REVISED` 0.6 BUY generator
- Fixed lot: 0.02
- Partial rule: close 50% at the engine's original structural target
- Runner rule: retain 50% toward target distance 2.5×
- Stop candidates: 1.5×, followed by 1.75× because 1.5× failed the gate

The replay is conservative when stop and partial/runner are touched in the same
M1 candle: it assigns the adverse ordering. A partial followed by a stop earns
the partial-target R on half the position and loses 1R on the remaining half.

## Replay result

| Metric | Baseline normal | Stop 1.5× / runner 2.5× | Stop 1.75× / runner 2.5× | Stop 2× / runner 2.5×, no partial |
|---|---:|---:|---:|---:|
| Executed trades | 1,434 | 1,004 | 959 | 919 |
| Runner TP | 546 | 300 | 319 | 328 |
| Full stop | 873 | 506 | 445 | 591 |
| Partial then stop | — | 195 | 193 | — |
| Partial taken | — | 495 | 512 | — |
| Skipped overlap | 0 | 424 | 469 | 509 |
| Rejected invalid target | 0 | 6 | 6 | 6 |
| Total R | **+176.443R** | +149.101R | +149.432R | +166.436R |
| Expectancy | +0.123R | +0.149R | +0.156R | **+0.181R** |
| Maximum drawdown | 59.479R | 22.236R | **16.602R** | 26.543R |
| First-obstacle room below 1R | 42 | 138 | 336 | 460 |
| Runner beyond first obstacle | — | 994 | 949 | 909 |
| Partial beyond first obstacle | — | 0 | 0 | — |

The partial target respects the first obstacle in both candidates, but nearly
every runner still crosses it without a modeled post-obstacle acceptance event.

## Fixed-lot cash path

| Setup | Start | Ending balance | Net | PF | Max DD / peak | Minimum balance | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| 1.5× / 2.5× partial | $50 | $1,217.96 | +$1,167.96 | 1.36 | **44.24%** | $44.36 | completed |
| 1.5× / 2.5× partial | $100 | $1,267.96 | +$1,167.96 | 1.36 | **37.67%** | $94.36 | completed |
| 1.75× / 2.5× partial | $50 | $1,549.49 | +$1,499.49 | **1.45** | 55.48% | $34.71 | completed |
| 1.75× / 2.5× partial | $100 | $1,599.49 | +$1,499.49 | **1.45** | 39.00% | $84.71 | completed |

Cash P/L is represented by the equivalent blended exit R. Adverse equity is
conservatively calculated as though the full lot remains exposed through the
trade's maximum adverse excursion; actual margin would decrease after the
partial fill.

## Gate decision

Both candidates have positive expectancy and complete the fixed-lot cash path,
but neither passes the official forward gate:

- total R is below the normal baseline;
- drawdown is above the 4R limit;
- first-obstacle room violations remain;
- runners cross the first obstacle without causal acceptance confirmation.

The 1.75× candidate improves R drawdown and cash profit factor over 1.5×. The
1.5× candidate has lower cash drawdown. Neither is frozen as an official
forward candidate. Production is unchanged, no forward task is registered,
and the conditional `goldm_bear` phase remains unstarted.

Commission, swap, slippage, and executable bid/ask differences are excluded.
No order was sent.
