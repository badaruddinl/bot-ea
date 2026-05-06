# GOLDm# High-Risk Micro Scalper Testing Protocol

This protocol keeps the EA inputs fixed. Backtest, OOS, and forward checks are separate evidence layers; none of them should be used to tune the baseline settings in `GoldMHighRiskMicroScalper_GOLDm.set`.

## Source Strategy

Baseline: `C:\Users\badaruddinl\Downloads\pilihan_strategi_final_ea_goldm_high_risk_scalper.md`

Implemented artifact:

- `D:\luthfi\project\bot-ea\mt5\Experts\bot-ea\GoldMHighRiskMicroScalper.mq5`
- `D:\luthfi\project\bot-ea\mt5\Profiles\Tester\GoldMHighRiskMicroScalper_GOLDm.set`

## Test Method

Use MetaTrader 5 Strategy Tester with:

- Symbol: `GOLDm#`
- Period: `M1`
- Model: `Every tick based on real ticks`
- Optimization: off
- Execution delay: fixed delay, default `100` ms in the script
- Deposit: can be small if the broker symbol allows it; `InpMinimumCapitalToTrade=0.0` disables the fixed USD floor and lets broker margin/min-lot checks decide
- Leverage: `1:1000`
- Inputs: fixed set file above

The active micro account gate is tuned for ultra-high risk: for a `5 USD` deposit, `MaxDailyLossPercent=80.0` and `MaxEquityDrawdownStop=80.0` allow trading down to roughly `1 USD` before new entries stop. `FreeMarginCheck=true` remains active, so broker margin can still block entries before that level.

The default fixed test split is:

- Backtest: `2026.01.01` to `2026.04.01`
- OOS: `2026.04.01` to `2026.05.01`
- Forward test: demo/live-shadow from `2026.05.05` onward, with the same set file and no parameter changes

## Commands

Install and compile:

```powershell
rtk powershell -ExecutionPolicy Bypass -File .\scripts\install-mt5-goldm-scalper.ps1
```

Run fixed-parameter backtest and OOS:

```powershell
rtk powershell -ExecutionPolicy Bypass -File .\scripts\run-mt5-goldm-backtests.ps1
```

The runner asks MT5 to write HTML reports under:

```text
D:\luthfi\project\bot-ea\data\backtests\goldm_high_risk_scalper\reports\
```

If MT5 does not emit HTML, use the tester `.tst` cache and logs under the terminal data folder. The run result summary for the first execution is recorded in `docs/goldm-high-risk-scalper-backtest-results.md`.

On this machine, command-line HTML reports did not get written because MT5 saves reports relative to `C:\Program Files\MetaTrader 5`, and that directory is not user-writable. The tester journal and `.tst` cache are the authoritative local outputs for these runs.

For micro-equity tests such as `5 USD`, run:

```powershell
.\scripts\run-mt5-goldm-backtests.ps1 -Deposit 5 -CloseRunningTerminal
```

Run tuning candidates without changing the EA logic:

```powershell
.\scripts\tune-mt5-goldm-scalper.ps1 -SkipInstall -CloseRunningTerminal -Deposit 5 -TopToValidate 8
```

The current selected tuned preset is `dense_entries_aggressive`, installed into `GoldMHighRiskMicroScalper_GOLDm.set`.

After the research-driven pass, the active preset was changed to `tight_spread_aggressive` because it had the least-bad OOS result among tested variants while preserving high trade count. It was still not profitable in the tested OOS window.

After raw candle mining, the active research preset was changed again to `mined_alt8_long_h20_runner`. It uses the mined sequence `UDUDUDUD` as a long-only trigger and much looser runner exits:

- `InpSignalModel=2`
- `InpMinedRuleMode=3`
- `InpMinedRawSequence=UDUDUDUD`
- `InpMaxPositions=1`
- `InpAllowAveraging=false`
- `InpMaxTotalOpenLot=0.10`
- `InpLockStartMin=1.50`
- `InpTrailBackMin=0.70`
- `InpEmergencySLMin=3.00`
- `InpMaxHoldSeconds=1200`

This preset is the current aggressive research baseline because it reached `8.55 USD` from a `5 USD` deposit in the March screen and `10.68 USD` in the Jan-Mar in-sample run. It failed OOS April and latest May, so it must not be treated as validated live-ready settings.

After the 2024 stress/deposit matrix, the active preset was changed to `adaptive_alt8_rsi50_wide_runner`. It keeps the same mined long-only sequence but adds a coarse RSI context gate and wider runner exits:

- `InpSignalModel=2`
- `InpMinedRuleMode=3`
- `InpMinedRawSequence=UDUDUDUD`
- `InpRSIPeriod=14`
- `InpUseMinedRSIFilter=true`
- `InpMinedMinRSI=50.0`
- `InpMaxTotalOpenLot=2.0`
- `InpLockStartMin=3.00`
- `InpTrailBackMin=1.20`
- `InpEmergencySLMin=5.00`
- `InpUseAdaptiveTradePause=true`

This preset still is not a validated profitable EA. It became the active research baseline because it materially reduced the full stress loss versus `mined_alt8_long_h20_runner` on deposits from `5` to `100 USD`.

After the $5 walk-forward and broader structure/Fibonacci research pass, the active research baseline was changed to `m1_later_lock4_sl7`. It keeps the same high-risk M1 raw-sequence scalper direction, but lets winners run longer and gives retracement more room:

- `InpSignalModel=2`
- `InpMinedRuleMode=3`
- `InpMinedRawSequence=UDUDUDUD`
- `InpRSIPeriod=14`
- `InpUseMinedRSIFilter=true`
- `InpMinedMinRSI=50.0`
- `InpMaxTotalOpenLot=2.0`
- `InpLockStartMin=4.00`
- `InpLockStartMax=10.00`
- `InpTrailBackMin=2.00`
- `InpTrailBackMax=6.00`
- `InpEmergencySLMin=7.00`
- `InpEmergencySLMax=18.00`
- `InpMaxHoldSeconds=1800`

This became active because it beat `adaptive_alt8_rsi50_wide_runner` on the same $5 full stress comparison: final balance `2.58 USD` with `545` trades versus `1.16 USD` with `110` trades. It is still not a validated profitable final/live preset because the full stress net remained negative.

Run the 2024 deposit matrix with:

```powershell
.\scripts\run-mt5-goldm-deposit-matrix.ps1 -CloseRunningTerminal
```

Current local MT5 real ticks for `GOLDm#` begin at `2024.11.07`, so a tester start date of `2024.01.01` does not mean real-tick coverage exists for the first ten months of 2024.

## Review Metrics

Do not accept net profit alone. Review:

- Profit factor
- Expected payoff
- Balance and equity drawdown
- Recovery factor
- Sharpe ratio
- Number of trades
- Consecutive wins/losses
- Average win/loss
- Holding time
- Trades per day
- Whether OOS behavior is materially worse than the backtest

## Sources

- MetaTrader 5 Strategy Testing: https://www.metatrader5.com/en/terminal/help/algotrading/testing
- MetaTrader 5 Real and Generated Ticks: https://www.metatrader5.com/en/terminal/help/algotrading/tick_generation
- MetaTrader 5 Tester Data Preparation: https://www.metatrader5.com/en/terminal/help/algotrading/test_preparation
- MetaTrader 5 Testing Report: https://www.metatrader5.com/en/terminal/help/algotrading/testing_report
- MetaTrader 5 command-line tester configuration: https://www.metatrader5.com/en/terminal/help/start_advanced/start
- MetaTrader 5 Strategy Optimization and Forward Testing: https://www.metatrader5.com/en/terminal/help/algotrading/strategy_optimization
