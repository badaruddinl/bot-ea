# GOLDM_REVISED 0.6.0 — USD 50/100, Jun–19 Aug 2026

## Scope

- Broker data: local MT5 `GOLD.i#`, account server `XMGlobal-MT5 5`
- Replay window: 2026-06-01 00:00 through 2026-08-19 10:05, GMT+3
- The live M5 candle beginning at 10:05 was excluded
- Fixed lot: 0.02; no compounding or dynamic position sizing
- Starting balances: USD 50 and USD 100
- Signal engine: frozen REVISED 0.6 BUY generator
- Normal execution is retained as the control
- Wide execution uses stop distance 2× and scales the distance from entry to
  the engine's original target

Every wide scenario is replayed independently on closed M1 bars. A subsequent
signal is skipped if the prior position remains open under that scenario.

## Baseline replay

Normal execution produced 20 BUY signals: 11 targets, eight stops, one
ambiguous same-M1-bar outcome, and no position open at the end. Total result
was `+13.516047R`, expectancy `+0.675802R`, and maximum drawdown `3R`.

## Fixed-lot balance comparison

Because every surviving scenario uses the same fixed 0.02 lot, its USD profit
is identical at both starting balances. The extra USD 50 changes percentage
return, relative drawdown, and margin headroom rather than trade P/L.

| Setup | Trades | TP / SL | Skipped | Expectancy | End at $50 | End at $100 | PF | DD peak at $50 / $100 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Normal control | 20 | 11 / 8 | 0 | **+0.676R** | $117.92 | $167.92 | **2.50** | **23.00% / 11.50%** |
| SL 2×, TP 1.00× | 20 | 13 / 7 | 0 | +0.195R | $87.96 | $137.96 | 1.46 | 46.00% / 23.00% |
| SL 2×, TP 1.25× | 20 | 10 / 10 | 0 | +0.009R | $48.91 | $98.91 | 0.99 | 47.98% / 26.53% |
| SL 2×, TP 1.50× | 19 | 10 / 9 | 1 | +0.169R | $87.24 | $137.24 | 1.38 | 46.00% / 23.00% |
| SL 2×, TP 1.75× | 19 | 10 / 9 | 1 | +0.276R | $109.55 | $159.55 | 1.61 | 46.00% / 23.00% |
| SL 2×, TP 2.00× | 19 | 10 / 9 | 1 | +0.383R | **$131.80** | **$181.80** | **1.84** | 46.00% / 23.00% |
| SL 2×, TP 2.10× | 19 | 9 / 10 | 1 | +0.283R | $100.56 | $150.56 | 1.44 | 46.00% / 23.00% |
| SL 2×, TP 2.15× | 19 | 9 / 10 | 1 | +0.303R | $104.45 | $154.45 | 1.48 | 46.00% / 23.00% |
| SL 2×, TP 2.20× | 19 | 9 / 10 | 1 | +0.322R | $108.33 | $158.33 | 1.51 | 46.00% / 23.00% |
| SL 2×, TP 2.25× | 19 | 9 / 10 | 1 | +0.341R | $112.24 | $162.24 | 1.55 | 46.00% / 23.00% |
| SL 2×, TP 2.30× | 19 | 9 / 10 | 1 | +0.360R | $116.10 | $166.10 | 1.58 | 46.00% / 23.00% |
| SL 2×, TP 2.35× | 19 | 9 / 10 | 1 | +0.380R | $119.98 | $169.98 | 1.61 | 46.00% / 23.00% |
| SL 2×, TP 2.40× | 19 | 9 / 10 | 1 | +0.399R | $123.87 | $173.87 | 1.65 | 46.00% / 23.00% |
| SL 2×, TP 2.50× | 19 | 9 / 10 | 1 | +0.438R | $131.63 | $181.63 | 1.72 | 46.00% / 23.00% |
| SL 2×, TP 3.00× | 19 | 8 / 11 | 1 | +0.390R | $108.80 | $158.80 | 1.46 | 46.00% / 25.94% |

All scenarios completed without insufficient margin or stop-out. Maximum
required margin was $8.84. Minimum simulated margin level was 454.52% for the
$50 normal control and 319.05% for the representative $50 wide-stop variants.

## Interpretation

The best wide-stop result in this shorter window is TP 2.00×: net profit is
$81.80, fractionally above TP 2.50× at $81.63, while profit factor is higher
and drawdown in dollars is lower. TP 1.25× is the only losing cash result.

The normal control remains substantially more efficient per unit of risk: it
has the highest R expectancy and profit factor, and half the relative drawdown
of the wide-stop family. At $50, the wide TP-2.00× candidate reaches 46% peak
drawdown versus 23% for normal. At $100 those figures fall to 23% and 11.5%
because the USD drawdown is unchanged at fixed lot.

This window contains only 20 original signals, so the shift from the earlier
TP-2.25× optimum to TP 2.00× is evidence of parameter instability rather than
proof of a new universal optimum. Normal, TP 2.00×, and TP 2.50× should remain
separate forward-test candidates instead of retuning the engine to this sample.

Cash calculations use MT5 `order_calc_margin` and `order_calc_profit` for the
connected broker contract. Commission, swap, slippage, and executable bid/ask
differences are not included. No order was sent.
