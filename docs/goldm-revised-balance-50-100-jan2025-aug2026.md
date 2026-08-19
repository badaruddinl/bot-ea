# GOLDM_REVISED 0.6.0 — USD 50/100, Jan 2025–19 Aug 2026

## Scope

- Broker data: local MT5 `GOLD.i#`, account server `XMGlobal-MT5 5`
- Replay window: 2025-01-01 00:00 through 2026-08-19 10:15, GMT+3
- Fixed lot: 0.02; no compounding or dynamic position sizing
- Starting balances: USD 50 and USD 100
- Signal engine: frozen REVISED 0.6 BUY generator
- Normal execution is retained as the control
- Wide execution uses stop distance 2× and scales the distance from entry to
  the engine's original target

The MT5 loader returned 577,958 M1 bars, beginning with the warm-up history on
2024-12-30. Every wide scenario is replayed independently; signals arriving
while its preceding position remains open are skipped.

## Baseline replay

Normal execution produced 412 BUY signals: 166 targets, 239 stops, seven
ambiguous same-M1-bar outcomes, and no open position at the end. Total result
was `+91.105164R`, expectancy `+0.221129R`, and maximum drawdown
`24.227544R`.

## USD 50 result

No USD 50 scenario survives the complete window.

| Setup | Planned trades | Completed before failure | Simulated residual | Failure |
|---|---:|---:|---:|---|
| Normal | 412 | 11 | $1.08 | stop-out, 2025-01-10 16:36 |
| SL 2×, TP 1.00× | 381 | 9 | $1.07 | stop-out |
| SL 2×, TP 1.25× | 342 | 9 | $1.07 | stop-out |
| SL 2×, TP 1.50× | 323 | 9 | $1.07 | stop-out |
| SL 2×, TP 1.75× | 311 | 9 | $1.07 | stop-out |
| SL 2×, TP 2.00× | 302 | 10 | $3.20 | insufficient margin |
| SL 2×, TP 2.10× | 299 | 10 | $4.47 | insufficient margin |
| SL 2×, TP 2.15× | 298 | 10 | $5.11 | insufficient margin |
| SL 2×, TP 2.20× | 298 | 10 | $1.08 | stop-out |
| SL 2×, TP 2.25× | 296 | 10 | $1.08 | stop-out |
| SL 2×, TP 2.30× | 291 | 10 | $1.08 | stop-out |
| SL 2×, TP 2.35× | 291 | 10 | $1.08 | stop-out |
| SL 2×, TP 2.40× | 287 | 10 | $1.08 | stop-out |
| SL 2×, TP 2.50× | 281 | 10 | $1.08 | stop-out |
| SL 2×, TP 3.00× | 269 | 8 | $1.07 | stop-out |

Residual values are outputs of the broker's simulated 20% stop-out threshold,
not balances that should be interpreted as a viable recovery path.

## USD 100 result

| Setup | Trades | TP / SL / ambiguous | Skipped | Expectancy | Ending balance | PF | Max DD / peak | Minimum balance | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Normal | 412 | 166 / 239 / 7 | 0 | +0.221R | $765.42 | 1.52 | 85.42% | $14.58 | completed |
| SL 2×, TP 1.00× | 381 | 224 / 154 / 3 | 31 | +0.200R | $1.09 | 0.22* | 99.05% | $1.09 | stop-out after 15 |
| SL 2×, TP 1.25× | 342 | 188 / 152 / 2 | 70 | +0.243R | $1.09 | 0.28* | 99.09% | $1.09 | stop-out after 15 |
| SL 2×, TP 1.50× | 323 | 166 / 155 / 2 | 89 | +0.280R | $1.09 | 0.28* | 99.07% | $1.09 | stop-out after 15 |
| SL 2×, TP 1.75× | 311 | 148 / 162 / 1 | 101 | +0.289R | $1.09 | 0.29* | 99.09% | $1.09 | stop-out after 15 |
| SL 2×, TP 2.00× | 302 | 140 / 161 / 1 | 110 | +0.370R | $1,425.24 | 1.76 | 84.01% | $19.80 | completed |
| SL 2×, TP 2.10× | 299 | 133 / 166 / 0 | 113 | +0.358R | $1,341.99 | 1.68 | 79.39% | $25.78 | completed |
| SL 2×, TP 2.15× | 298 | 133 / 165 / 0 | 114 | +0.385R | $1,418.92 | 1.73 | 78.06% | $27.59 | completed |
| SL 2×, TP 2.20× | 298 | 132 / 166 / 0 | 114 | +0.395R | $1,477.48 | 1.76 | 76.87% | $29.24 | completed |
| SL 2×, TP 2.25× | 296 | 129 / 167 / 0 | 116 | +0.392R | $1,486.82 | 1.77 | 76.22% | $30.21 | completed |
| SL 2×, TP 2.30× | 291 | 124 / 167 / 0 | 121 | +0.387R | $1,424.63 | 1.73 | 75.58% | $31.17 | completed |
| SL 2×, TP 2.35× | 291 | 124 / 167 / 0 | 121 | +0.406R | $1,470.56 | 1.76 | 74.95% | $32.14 | completed |
| SL 2×, TP 2.40× | 287 | 120 / 167 / 0 | 125 | +0.399R | $1,445.60 | 1.74 | 74.32% | $33.11 | completed |
| SL 2×, TP 2.50× | 281 | 116 / 165 / 0 | 131 | +0.399R | **$1,520.85** | **1.81** | **73.08%** | **$35.05** | completed |
| SL 2×, TP 3.00× | 269 | 100 / 169 / 0 | 143 | +0.412R | $3.44 | 0.12* | 96.92% | $3.44 | insufficient margin after 12 |

`*` Profit factor for failed scenarios only describes trades completed before
failure and is not comparable with a full-window profit factor.

## Interpretation

USD 50 at fixed 0.02 lot is conclusively too small for this window. USD 100
survives only for normal execution and the wide target plateau from 2.00×
through 2.50×. Target 2.50× is the strongest surviving wide candidate: it has
the highest ending balance and profit factor, the lowest peak-relative
drawdown in the surviving plateau, and the highest minimum balance.

The absolute returns do not make USD 100 low-risk. Normal execution falls to a
$14.58 realized balance, and even target 2.50× reaches 73.08% peak-relative
drawdown. Commission, swap, slippage, or a different trade sequence could turn
these narrow survival margins into failure.

The optimum also changes by window: TP 2.00× led the June-only sample while TP
2.50× leads this longer sample. This confirms parameter instability and argues
for keeping normal, TP 2.00×, and TP 2.50× as separate forward-test candidates
rather than selecting a universal multiplier from in-sample balance.

Cash calculations use MT5 `order_calc_margin` and `order_calc_profit` for the
connected broker contract. Commission, swap, slippage, and executable bid/ask
differences are not included. No order was sent.
