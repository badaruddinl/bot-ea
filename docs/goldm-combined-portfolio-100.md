# GOLDM combined BUY/SELL portfolio — one USD 100 balance

## Architecture

One portfolio script consumes BUY REVISED and SELL bear event streams but owns
one mutable account state:

```text
one balance
one shared margin pool
one floating equity curve
BUY and SELL may overlap
```

Both sides use fixed lot 0.02. Position profit is calculated with MT5 contract
metadata. Floating equity is evaluated on every M1 bar at one common market
price; BUY-low and SELL-high are not incorrectly summed as simultaneous worst
prices. Commission, swap, slippage, and executable bid/ask spread are excluded.

## Shared-account result

| Window | Closed / requested | Ending balance | Net | Max concurrent | Max shared margin | Minimum floating equity | Floating DD | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 4–19 Aug | 14 / 14 | $261.19 | +$161.19 | 1 | $8.84 | $87.65 | 17.09% | completed |
| Jan 2025–now | 359 / 359 | $1,803.37 | +$1,703.37 | 2 | $19.23 | $45.96 | 25.08% | completed |
| Nov–Feb | 80 / 80 | $615.70 | +$515.70 | 1 | $10.77 | $33.21 | 26.42% | completed |
| Jun–now | 10 / 33 | **$1.60** | **-$98.40** | 1 | $8.93 | $0.22 | **99.85%** | **shared stop-out** |
| Full suite | 1,268 / 1,268 | $2,639.37 | +$2,539.37 | 2 | $19.23 | $74.42 | 17.40% | completed |

The full-suite account survives because early-year profit builds capital before
the later loss sequence. The June-starting account has no such buffer and
reaches the broker's 20% stop-out threshold after ten positions. Maximum
concurrency is only one in that window, proving the failure is caused by the
combined trade sequence on one USD 100 capital base, not simultaneous margin.

## Decision

Do not deploy the two fixed-lot engines together on one USD 100 balance. The
combined portfolio fails the mandatory June partial window. Full-suite ending
balance must not override this start-date failure.

The script is research-only. It sends no orders and does not change either
engine or production.

## USD 100,000 balance with fixed 0.20 lot on both sides

The same one-balance/shared-margin simulation was rerun with USD 100,000 and
fixed 0.20 lot for both BUY and SELL.

| Window | Closed | Ending balance | Net / return | Max concurrent | Max margin | Minimum floating equity | Floating DD | Result |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| 4–19 Aug | 14 / 14 | $101,612.09 | +$1,612.09 / 1.612% | 1 | $88.43 | $99,876.55 | 0.585% | completed |
| Jan 2025–now | 359 / 359 | $117,037.92 | +$17,037.92 / 17.038% | 2 | $192.27 | $99,459.85 | 4.026% | completed |
| Nov–Feb | 80 / 80 | $105,158.01 | +$5,158.01 / 5.158% | 1 | $107.71 | $99,332.43 | 2.058% | completed |
| Jun–now | 33 / 33 | $102,552.35 | +$2,552.35 / 2.552% | 2 | $160.10 | $98,963.49 | 1.716% | completed |
| Full suite | 1,268 / 1,268 | **$125,408.85** | **+$25,408.85 / 25.409%** | 2 | $192.27 | $99,744.50 | **3.759%** | completed |

This capitalization/lot pair completes the evidence window, all three partial
windows, and the full suite without shared stop-out or insufficient margin. It
uses fixed lots and is not compounding. Costs and executable spread remain
excluded, so it is historical research evidence rather than deployment
authorization.
