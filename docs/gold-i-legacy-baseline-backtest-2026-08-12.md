# GOLD.i# Legacy Baseline Backtest — 2026-08-12

This run is a broker-compatibility baseline for the legacy
`GoldMHighRiskMicroScalper` EA. It is **not** a backtest of the new GoldM Sniper
signal-only strategy, whose D1/H4/H1 context and M15 breakout–retest engine have
not yet been implemented.

## Configuration

- Terminal/server: MetaTrader 5 / `XMGlobal-MT5 5`
- Symbol: `GOLD.i#`
- Period: M1
- Model: every tick based on real ticks
- Execution delay: 100 ms
- Initial deposit: USD 100
- Leverage: 1:1000
- Legacy entry model: mined `UDUDUDUD`, long-only research baseline
- Auto execution: enabled inside Strategy Tester only

Runtime symbol metadata matched the supplied broker specification:

```text
minimum lot  : 0.01
maximum lot  : 50.00
volume step  : 0.01
contract     : 100.00
tick size    : 0.01
tick value   : 1.00
point        : 0.01
stops level  : 0
```

Real ticks in the local tester begin at `2026-05-01 00:00:00`.

## Backtest: 2026-05-01 through 2026-07-31

| Metric | Result |
| --- | ---: |
| Initial balance | USD 100.00 |
| Final balance | USD 22.10 |
| Net | **USD -77.90** |
| Profit factor | **0.5214** |
| Exits | 39 |
| Wins / losses | 23 / 16 |
| Win rate | 58.97% |
| Expected payoff | USD -1.99744 |
| Average win | USD 3.68957 |
| Average loss | USD -10.17250 |
| Maximum win | USD 10.09 |
| Maximum loss | USD -72.80 |
| Maximum consecutive losses | 3 |
| Ticks / bars | 25,467,958 / 90,359 |

The average loss was approximately `2.76×` the average win. The test also logged
one attempted close after the position no longer existed, which indicates a legacy
close-path race that must not be carried into the signal-only service.

## OOS: 2026-08-01 through 2026-08-11

| Metric | Result |
| --- | ---: |
| Initial balance | USD 100.00 |
| Final balance | USD 67.90 |
| Net | **USD -32.10** |
| Profit factor | **0.8544** |
| Exits | 11 |
| Wins / losses | 7 / 4 |
| Win rate | 63.64% |
| Expected payoff | USD -2.91818 |
| Average win | USD 26.91714 |
| Average loss | USD -55.13000 |
| Maximum win | USD 61.60 |
| Maximum loss | USD -141.40 |
| Maximum consecutive losses | 2 |
| Ticks / bars | 2,444,168 / 9,652 |

The average loss was approximately `2.05×` the average win. Auto equity sizing
increased volume to `0.20` lot during the run, demonstrating why this legacy sizing
policy is unsuitable for the new signal-only architecture.

## Evidence files

Tester cache:

```text
C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\Tester\cache\GoldMHighRiskMicroScalper.GOLD.i#.M1.20260501_20260801.4.79C0BF72BFCD00BE7CA79830AF467D72.tst
C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\Tester\cache\GoldMHighRiskMicroScalper.GOLD.i#.M1.20260801_20260812.4.79C0BF72BFCD00BE7CA79830AF467D72.tst
```

Agent journal:

```text
C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\logs\20260812.log
```

The command-line tester again did not emit HTML reports. The `.tst` cache and
agent journal are the authoritative local outputs.

## Decision

Reject the legacy M1 mined-sequence alpha for `GOLD.i#`. Both the main window and
OOS window have negative expectancy and profit factor below 1.0. A high win rate
does not compensate for the loss asymmetry.

The next valid backtest must target the new deterministic signal definition:
D1/H4/H1 context, objective levels, M15 breakout and retest, M5 trigger,
minimum 3R room, no order execution, and outcome labeling in R units.
