# GOLDm# High-Risk Micro Scalper Backtest Results

Run date: 2026-05-05

Terminal:

- MetaTrader 5 build 5833
- Server: `XMGlobal-MT5 14`
- Symbol: `GOLDm#`
- Period: `M1`
- Model: `Every tick based on real ticks`
- Execution delay: `100` milliseconds
- Deposit: `100.00 USD`
- Leverage: `1:1000`
- Optimization: off
- Inputs: `GoldMHighRiskMicroScalper_GOLDm.set`

## Backtest

Period: `2026.01.01` to `2026.04.01`

- Result: `99.84 USD` final balance from `100.00 USD`
- Net: `-0.16 USD`
- Trades: 1 opened position, closed by stop loss
- Entry: `2026.01.02 08:06:00`, buy `0.10` lot at `4375.91`
- Exit: `2026.01.02 08:09:22`, stop loss sell at `4374.34`
- Ticks: `24,793,081`
- Bars: `86,135`
- Tester duration: `0:01:38.149`

## OOS

Period: `2026.04.01` to `2026.05.01`

- Result: `99.96 USD` final balance from `100.00 USD`
- Net: `-0.04 USD`
- Trades: 1 opened position, closed by reverse signal
- Entry: `2026.04.01 01:19:08`, buy `0.10` lot at `4671.47`
- Exit: `2026.04.01 01:19:11`, sell close at `4671.03`
- Ticks: `7,729,108`
- Bars: `28,953`
- Tester duration: `0:00:39.409`

## Notes

MT5 did not write the configured HTML report path, but it did complete both tester runs and created `.tst` cache files under the terminal data folder:

- `C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\Tester\cache\GoldMHighRiskMicroScalper.GOLDm#.M1.20260101_20260401.4.44F4DA83B2430B0112BB6E0373F74189.tst`
- `C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\Tester\cache\GoldMHighRiskMicroScalper.GOLDm#.M1.20260401_20260501.4.44F4DA83B2430B0112BB6E0373F74189.tst`

Primary logs:

- `C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Terminal\D0E8209F77C8CF37AD8BF550E51FF075\Tester\logs\20260505.log`
- `C:\Users\badaruddinl\AppData\Roaming\MetaQuotes\Tester\D0E8209F77C8CF37AD8BF550E51FF075\Agent-127.0.0.1-3000\logs\20260505.log`

Forward test was not simulated from historical data. It should be run as demo/live-shadow from `2026-05-05` onward using the same `.set` file, with no parameter changes.

## Recheck

Recheck run date: `2026-05-05`

Findings:

- The configured MT5 HTML report path was not written because MT5 command-line reports are relative to the platform directory. On this machine that is `C:\Program Files\MetaTrader 5`, which is not user-writable. The tester still runs and writes `.tst` cache plus journal logs.
- The `100 USD` test produced only one trade because `InpMinimumCapitalToTrade=100.0`. After the first loss, balance/equity dropped below `100`, so the risk gate intentionally blocked all new entries.
- This was verified by a diagnostic MT5 rerun with the same EA inputs and the same `GoldMHighRiskMicroScalper_GOLDm.set`.

Diagnostic rerun with `Deposit=100`:

- Backtest `2026.01.01` to `2026.04.01`: final balance `99.84`; opened buy `1`, opened sell `0`; `canOpenBlocked=24,792,147`.
- OOS `2026.04.01` to `2026.05.01`: final balance `99.96`; opened buy `1`, opened sell `0`; `canOpenBlocked=7,729,102`.

Control rerun with `Deposit=150`, same `.set` file:

- Backtest `2026.01.01` to `2026.04.01`: final balance `135.11`; opened buy `759`, opened sell `329`; `canOpenOk=123,170`.
- OOS `2026.04.01` to `2026.05.01`: final balance `134.92`; opened buy `268`, opened sell `308`; `canOpenOk=61,600`.

Conclusion at that point: the first implementation treated `MinimumCapitalToTrade=100.0` as a hard floor. That was too conservative for XM `GOLDm#`, whose tested properties were `minLot=0.1000`, `contract=1.00`, `tickSize=0.01000`, `tickValue=0.01000`, and `leverage=1:1000`.

## Micro-Equity Correction

The EA was corrected so micro accounts are governed by broker openability instead of a fixed USD floor:

- `InpMinimumCapitalToTrade=0.0`
- If equity is below the first lot step, auto lot falls back to `SYMBOL_VOLUME_MIN`.
- The EA still checks free margin with `OrderCalcMargin` before opening.

This keeps `GOLDm#` usable for very small equity while preserving spread, daily-loss, drawdown, basket-loss, cooldown, and margin gates.

Micro-equity verification with `Deposit=5`, same corrected `.set` file:

- Backtest `2026.01.01` to `2026.04.01`: final balance `4.45`; opened buy `32`, opened sell `0`; `canOpenOk=3,784`.
- OOS `2026.04.01` to `2026.05.01`: final balance `4.43`; opened buy `32`, opened sell `6`; `canOpenOk=1,991`.

This confirms `GOLDm#` can run at `5 USD` under the tested broker properties. Below the first sizing step, the EA uses broker minimum lot `0.10`, so risk is no longer smoothly proportional to equity; it is bounded by the broker minimum volume.

## Ultra-High-Risk Micro Gate Correction

The `5 USD` micro-equity run still stopped around the `4 USD` area because the MD baseline risk gates were conservative in percentage terms:

- `MaxDailyLossPercent=5.0`
- `MaxEquityDrawdownStop=10.0`
- `MaxConsecutiveLoss=3`
- `PauseAfterLossMinutes=10`
- `MaxBasketFloatingLossPercent=1.5`

On a `5 USD` account, those gates stop new entries after roughly `0.25` to `0.50 USD` of loss. To match the intended ultra-high-risk micro behavior, the active `.set` was changed to keep trading until around `1 USD` equity on a `5 USD` deposit:

- `MaxDailyLossPercent=80.0`
- `MaxEquityDrawdownStop=80.0`
- `MaxConsecutiveLoss=999`
- `PauseAfterLossMinutes=0`
- `MaxBasketFloatingLossPercent=80.0`

The strategy direction was not changed. Entry mode, indicators, score thresholds, spread filter, profit lock, emergency SL, max positions, auto lot, and margin check remained the same.

Verification with `Deposit=5`, real ticks, `100 ms` delay:

- Backtest `2026.01.01` to `2026.04.01`: final balance `0.88`; opened buy `321`, opened sell `0`; `canOpenOk=45,488`.
- OOS `2026.04.01` to `2026.05.01`: final balance `1.00`; opened buy `134`, opened sell `4`; `canOpenOk=400`.

This confirms the EA no longer stops in the `4 USD` area. It continues until the `80%` loss floor is reached or margin/spread/entry gates block individual trades.

## Ultra-High-Risk Tuning Pass

After the risk gate was changed to the `80%` micro-account floor, the EA was tuned again without changing strategy direction. The active selected variant is `dense_entries_aggressive`.

Changed inputs versus the `80%` risk-gate baseline:

- `TrendThreshold=60`
- `RangeThreshold=65`
- `TrendAddThreshold=65`
- `RangeAddThreshold=70`
- `MinDistanceBetweenEntryMin=0.05`
- `MinDistanceBetweenEntryATRMult=0.15`
- `CooldownAfterEntrySeconds=1`
- `CooldownAfterCloseSeconds=1`

Unchanged core strategy:

- `GOLDm#`, `M1`, `M5` confirmation
- EMA 8/21, EMA 50 M5, RSI 2, ATR 14, ADX 7, Donchian 5, Bollinger 20/2
- Trend/range/no-trade regime logic
- `MaxSpread=0.30`, `HardMaxSpread=0.50`
- Dynamic profit lock
- Emergency SL
- Auto lot from balance/equity with broker min-lot fallback
- `MaxPositions=3`, no buy/sell same time, same-direction averaging only
- `FreeMarginCheck=true`

Tuning screen `2026.03.01` to `2026.04.01`, `Deposit=5`:

- Baseline micro: final balance `1.07`, trades `140`, OnTester `0.50997506234414`
- Dense entries aggressive: final balance `1.00`, trades `144`, OnTester `0.507389162561576`

Validation after selecting `dense_entries_aggressive` as the active `.set`:

- Backtest `2026.01.01` to `2026.04.01`: final balance `1.04`; opened buy `409`, opened sell `0`; `canOpenOk=31,723`; OnTester `0.6658227848101261`.
- OOS `2026.04.01` to `2026.05.01`: final balance `1.00`; opened buy `140`, opened sell `5`; `canOpenOk=473`; OnTester `0.3067590987868285`.

This preset is more active than the `80%` baseline and still reaches the intended `~1 USD` floor instead of stopping around `4 USD`.

## Research-Driven Tuning Pass

The loss diagnosis after adding performance logging:

- Backtest dense active: `409` exits, win rate `56.97%`, gross profit `7.89`, gross loss `-11.85`, PF `0.6658`, expected payoff `-0.00968`.
- OOS dense active: `145` exits, win rate `23.45%`, gross profit `1.77`, gross loss `-5.77`, PF `0.3068`, expected payoff `-0.02759`.

Main causes:

- The EA was effectively a trend-buy scalper. In the dense Q1 run it opened `409` buys and `0` sells.
- OOS win rate collapsed to `23.45%`.
- Average win and average loss were too close in OOS (`0.05206` vs `-0.05393`) while win rate was low.
- Range entries were almost inactive.
- Profit factor stayed below `1.0` in every tested variant.

New testable inputs were added:

- DI confirmation from ADX: `InpUseDIDirectionFilter`, `InpMinDIDifference`
- ADX rising filter: `InpUseAdxRisingFilter`
- Spread-to-ATR gate: `InpUseSpreadAtrGate`, `InpMaxSpreadATRMult`, `InpMinAtrSpreadRatio`
- Cost-aware profit lock: `InpUseCostAwareProfitLock`, spread multipliers
- Reverse close debounce: `InpReverseCloseMinSeconds`, `InpReverseCloseOppositeScore`, `InpWeakSignalCloseScore`
- Pullback trend entry mode: `InpTrendEntryMode`, `InpTrendPullbackATRMult`
- RSI thresholds: `InpRSIOversold`, `InpRSIOverbought`
- Bollinger proximity by ATR: `InpBandProximityATRMult`

Targeted research-tuning results with `Deposit=5`:

- `baseline_micro` OOS: final `1.00`, PF `0.3068`, trades `145`.
- `pullback_dense` OOS: final `1.00`, PF `0.2278`, trades `124`.
- `pullback_tight_sl` OOS: final `0.93`, PF `0.2248`, trades `97`.
- `rsi_relaxed_range` OOS: final `1.00`, PF `0.3209`, trades `139`.
- `tight_sl_dense` OOS: final `0.91`, PF `0.3138`, trades `116`.
- `tight_spread_aggressive` OOS: final `1.02`, PF `0.3549`, trades `147`, opened buy `99`, opened sell `48`.

Selected active preset after this pass: `tight_spread_aggressive`, because it had the best OOS final balance and profit factor among tested variants while keeping high trade volume. It changes:

- `InpMaxSpread=0.25`
- `InpCooldownAfterEntrySeconds=3`
- `InpCooldownAfterCloseSeconds=2`

The result is still not profitable. The selected preset is only the least-bad OOS variant from this batch, not a validated profitable EA.

## Raw Candle Mining And Runner Pass

The next pass mined `GOLDm#` M1 candles directly from MT5 history.

- Data available from MT5: `99,780` M1 bars
- Range: `2026-01-22 04:32 UTC` to `2026-05-05 15:35 UTC`
- Train split: before `2026-04-01`
- OOS split: `2026-04-01` to `2026-05-01`
- Latest split: `2026-05-01` onward

The important finding was that the previous micro exits were too small for the mined horizons. Earlier presets commonly had average wins around `0.03 USD` and average losses around `-0.07 USD` on a `0.10` lot. To grow a `5 USD` balance to `6 USD`, the EA needs about `+1.00 USD` net, but a `0.03 USD` average winner requires more than thirty net winners before losses. Losses were erasing two to three wins at a time.

MFE/MAE from the mined data showed that useful 10-20 candle moves often travel several price dollars before completing:

- `raw_seq9_up_long` H20 OOS: MFE median `8.77`, MFE 70th percentile `13.64`, MAE 30th percentile `-5.72`
- `core_ema9_20_long` H20 OOS: MFE median `5.61`, MFE 70th percentile `9.50`, MAE 30th percentile `-8.76`
- `rsi14_revert_long` H10 OOS: MFE median `4.17`, MFE 70th percentile `6.65`, MAE 30th percentile `-7.11`

Because of that, new sequence modes were added to the EA:

- `SIGNAL_MODEL_MINED_RULES`
- `MINED_RULE_RAW_SEQUENCE_LONG`
- `MINED_RULE_RAW_SEQUENCE_SHORT`
- `InpMinedRawSequence`

Runner candidates used longer exits:

- `MaxHoldSeconds=1200`
- `UseAtrTakeProfit=false`
- `LockStartMin=1.50` to `2.00`
- `TrailBackMin=0.70` to `0.80`
- `EmergencySLMin=3.00`
- single-position variants with `MaxPositions=1`, `MaxTotalOpenLot=0.10`

Runner screen `2026.03.01` to `2026.04.01`, `Deposit=5`:

- `mined_alt8_long_h20_runner`: final `8.55`, trades `31`, PF `2.2241`
- `mined_seq7up_h20_runner_stack`: final `6.59`, trades `60`, PF `1.1506`
- `mined_seq7up_h20_runner`: final `6.16`, trades `48`, PF `1.1358`
- `mined_core_ema_h20_runner_wide`: final `1.65`, trades `114`, PF `0.8511`
- `mined_alt8_short_h20_runner`: final `1.57`, trades `21`, PF `0.4117`

Validation of the best screen candidate:

- `mined_alt8_long_h20_runner` in-sample `2026.01.01` to `2026.04.01`: final `10.68`, trades `294`, PF `1.1322`
- `mined_alt8_long_h20_runner` OOS `2026.04.01` to `2026.05.01`: final `2.94`, trades `57`, PF `0.7497`
- `mined_alt8_long_h20_runner` latest `2026.05.01` to `2026.05.06`: final `4.47`, trades `4`, PF `0.2933`

The active preset was changed to `mined_alt8_long_h20_runner` as a research baseline because it is the first tested configuration that clearly pushed a `5 USD` account above `6 USD`. It is not accepted as a robust final/live preset because it failed OOS and latest validation.

Why the older runs usually fell to `1 USD` within a few days:

- Broker minimum lot `0.10` prevents smooth risk scaling below `100 USD`; at `5 USD`, every trade is already high-risk.
- Leverage lowers margin, but it does not reduce P/L per price move.
- Previous profit locks and TP values captured very small wins while SL/emergency exits were materially larger.
- Win rate was not high enough to compensate for the win/loss asymmetry.
- Spread and slippage consumed a large part of each micro target.
- The original 60-180 second exits often cut positions before the 10-20 candle move that appeared in the mining data.

## 2024 Stress And Deposit Matrix

Run date: `2026-05-06`

Command:

```powershell
.\scripts\run-mt5-goldm-deposit-matrix.ps1 -CloseRunningTerminal
```

Tester settings:

- Symbol: `GOLDm#`
- Period: `M1`
- Model: every tick based on real ticks
- Execution delay: `100 ms`
- From: `2024.01.01`
- To: `2026.05.06`
- Leverage: `1:1000`

Important data limitation: MT5 accepted the `2024.01.01` start date, but the tester log reported real ticks beginning at `2024.11.07 00:00:00`. The test is therefore a local MT5 stress test over the available real-tick range, not full real-tick coverage from January 2024.

Results:

| Variant | Deposit | Final Balance | Net | Trades |
|---|---:|---:|---:|---:|
| `mined_alt8_long_h20_runner` | `5` | `0.92` | `-4.08` | `115` |
| `adaptive_alt8_rsi50_wide_runner` | `5` | `1.16` | `-3.84` | `110` |
| `mined_alt8_long_h20_runner` | `10` | `2.10` | `-7.90` | `292` |
| `adaptive_alt8_rsi50_wide_runner` | `10` | `1.86` | `-8.14` | `505` |
| `mined_alt8_long_h20_runner` | `20` | `3.93` | `-16.07` | `626` |
| `adaptive_alt8_rsi50_wide_runner` | `20` | `15.85` | `-4.15` | `701` |
| `mined_alt8_long_h20_runner` | `30` | `5.96` | `-24.04` | `1067` |
| `adaptive_alt8_rsi50_wide_runner` | `30` | `25.85` | `-4.15` | `701` |
| `mined_alt8_long_h20_runner` | `50` | `18.00` | `-32.00` | `1638` |
| `adaptive_alt8_rsi50_wide_runner` | `50` | `45.85` | `-4.15` | `701` |
| `mined_alt8_long_h20_runner` | `100` | `68.00` | `-32.00` | `1638` |
| `adaptive_alt8_rsi50_wide_runner` | `100` | `95.85` | `-4.15` | `701` |
| `adaptive_alt8_rsi50_wide_runner_scaled_lot` | `200` | `195.24` | `-4.76` | `701` |
| `adaptive_alt8_rsi50_wide_runner_scaled_lot` | `500` | `481.78` | `-18.22` | `701` |
| `adaptive_alt8_rsi50_wide_runner_scaled_lot` | `1000` | `957.48` | `-42.52` | `701` |

Interpretation:

- `adaptive_alt8_rsi50_wide_runner` is not profitable over this stress period, but it is materially better than the pushed baseline for deposits `5`, `20`, `30`, `50`, and `100`.
- At `10 USD`, the adaptive variant had more trades (`505` vs `292`) but slightly worse final balance.
- The original `200+` matrix entries were invalid because auto sizing requested `0.20+` lot while `InpMaxTotalOpenLot=0.10`; entries were blocked before trading started.
- The active adaptive preset was corrected to `InpMaxTotalOpenLot=2.0` and retested for `200`, `500`, and `1000 USD`. Lot scaling then worked and all three deposits produced `701` trades.

Selected active research preset after this matrix: `adaptive_alt8_rsi50_wide_runner`.
