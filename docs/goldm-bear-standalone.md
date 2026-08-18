# GOLDM Standalone Bear Engine

## Scope

`goldm_bear` is a research-only SELL engine for `GOLD.i#` M15. It does not
import, call, subclass, or copy the production `goldm_signal` strategy or the
`GoldMSniperParity` EA. It consumes closed OHLC bars and emits `WAIT`, `WATCH`,
or `SELL`; it has no order-placement function.

The visual specification came from the supplied 18 August 2026 chart. The
chart shows:

1. a large bearish displacement from the 4430s into the 4390s;
2. a range below the displacement origin;
3. repeated pullbacks that fail around lower resistance;
4. bearish continuation after the pullback near 09:45 and again near 13:15;
5. support around the low 4390s, making a target far below that area unsafe
   without a confirmed breakdown.

Times on that chart are broker-server time. On 18 August the broker is on
summer time, so server time is `GMT+3`.

## Broker profile used

| Property | Value |
| --- | --- |
| Symbol | `GOLD.i#` |
| Instrument | GOLD |
| Timeframe | M15 |
| Summer server offset | GMT+3 |
| Winter server offset | GMT+2 |
| Quote session | 01:00–23:59 (Friday to 23:58) |
| Trade session | 01:02–23:58 |
| Contract size | 100 troy ounces |
| Minimum price fluctuation | USD 0.01 |
| Minimum / maximum trade size | 0.01 / 50 lots |
| Stops level | 0 points |
| Advertised minimum spread | USD 0.20 |

The engine does not size or place trades, so leverage and lot limits are stored
only as research context. Price plans are rounded to USD 0.01 and assume at
least USD 0.20 spread when constructing the stop buffer.

## Signal model

### 1. Bear regime

The latest 32 closed bars must show both:

- a normalized linear-regression slope no steeper than a mild 0.025 ATR/bar
  countertrend pullback; and
- a drop of at least 1.25 ATR from the recent regime high.

This deliberately permits a sideways or mildly rising consolidation after a
strong bearish impulse. Requiring every recent swing to be a lower low would
reject the chart setup and be unnecessarily conservative. Entry still requires
a failed resistance retest followed by a close below the preceding candle low.

### 2. Pullback resistance

Resistance candidates are independently derived from:

- confirmed local swing highs; and
- psychological prices at USD 10, USD 50, and USD 100 intervals.

A bar enters `WATCH` when it retests a resistance within 0.28 ATR but has not
yet rejected it. A closed bearish body or upper-wick rejection upgrades the
setup to a SELL candidate. A close through the resistance cancels it; a close
more than 1.25 ATR below resistance is treated as a chased move.

### 3. Stop and targets

- Stop: above the rejection high/resistance plus the larger of 0.18 ATR or two
  spreads.
- TP1: slightly above the nearest structural support or psychological level.
- TP2: slightly above the next barrier, reported separately.
- Minimum space: 0.60 ATR before TP1.
- Minimum planned reward/risk: 0.70.

The relatively low 0.70 threshold is intentional. It allows high-probability
continuation entries with nearby support while still rejecting trades whose
first barrier leaves almost no room. It must be validated out of sample before
use with money.

### 4. Early close

An ordinary pullback does not close a SELL. The exit model waits for one of:

- TP touched;
- stop touched;
- two closed bars above structural resistance plus an ATR buffer; or
- one strong bullish displacement close above that invalidation level.

This directly addresses the observed early-close case: temporary retracement
is not treated as a failed forecast while bearish structure remains intact.

## Research basis

- Osler found that published support/resistance levels had predictive power for
  intraday trend interruptions. This supports treating levels as probabilistic
  barriers rather than exact prices: [Federal Reserve Bank of New York,
  *Support for Resistance*](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf).
- Osler's order-level research found stop-loss and take-profit orders clustered
  at round numbers, with reversals near levels and acceleration after genuine
  breaks. The engine therefore distinguishes rejection from breakout:
  [Federal Reserve Bank of New York Staff Report 125](https://www.newyorkfed.org/research/staff_reports/sr125.html).
- Lo, Mamaysky, and Wang demonstrate why visual patterns should be translated
  into explicit algorithms and tested statistically instead of judged by eye:
  [NBER Working Paper 7613](https://www.nber.org/papers/w7613).
- MT5 stores Python bar timestamps in UTC and only returns history available in
  the terminal. The MT5 adapter requests UTC and converts output to server time:
  [MetaTrader 5 Python `copy_rates_from` reference](https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesfrom_py).
- Symbol point and spread are read from MT5 symbol metadata rather than assumed
  during live data import: [MetaTrader 5 `symbol_info` reference](https://www.mql5.com/en/docs/python_metatrader5/mt5symbolinfo_py).

These sources motivate the features; they do not prove profitability for this
broker symbol. GOLD-specific thresholds require walk-forward validation on the
broker's own M15 bars and spreads.

## Usage

Scan a CSV whose timestamps are in broker-server time:

```powershell
goldm-bear-scan bars.csv --symbol GOLD.i# --server-utc-offset +03:00 --all-signals
```

Read bars directly from the already configured MT5 terminal without placing an
order:

```powershell
python scripts/run-goldm-bear-mt5.py `
  --symbol GOLD.i# `
  --from-server-time 2026-08-17T00:00:00 `
  --to-server-time 2026-08-19T00:00:00 `
  --server-utc-offset +03:00
```

CSV columns are `time,open,high,low,close` with optional `tick_volume` and
`spread`. `spread` is a price amount, not points.

## Promotion gate

The package must remain research-only until it has:

1. broker-native M15 data covering multiple regimes, not only 17–18 August;
2. walk-forward folds with spread and slippage stress;
3. comparison against no psychological-level filter and no structural target;
4. separate metrics for `WATCH`, confirmed SELL, TP1, TP2, invalidation, and
   maximum adverse excursion; and
5. manual reconciliation of the 14:00 early-close and 17:00 overextended-TP
   examples.
