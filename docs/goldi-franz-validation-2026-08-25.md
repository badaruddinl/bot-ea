# GOLDI_FRANZ_SHAKEOUT validation — 2026-08-25

## Identity and safety

- Baseline: `9ab3646b079657a89f20e5cab1cb6e2dc946056b`.
- Implementation commit: `27f72d8` plus its two preceding implementation
  commits on `feature/goldi-franz-shakeout`.
- Strategy/profile: `GOLDI_FRANZ_SHAKEOUT` `0.1.0`, `GOLD.i#`, magic
  `26081914`.
- Tester-only: `OnInit()` refuses every non-Strategy-Tester environment.
- No DEMO chart attach, Telegram delivery, REAL authority, or release binary
  installation was performed.

## Verification completed

- MetaEditor: `0 errors, 0 warnings`.
- Final EX5 SHA-256:
  `B8CF71EFFEF251C637C42794D7D00C36A4103562D73A195DFFF7178363F3E6A8`.
- Native harness on 331,446 real ticks: `FRANZ_HARNESS passed=true`, authority
  disabled, zero orders, tester PASS.
- Full Python/static regression: `858 passed`, `154 deselected`, 77 subtests;
  two pre-existing collection warnings.
- One-day performance smoke: 331,446 ticks in 2.044 seconds after scheduler
  optimization.

The harness covers BUY/SELL Fibonacci symmetry, dual trendline zones,
supply/demand proximal/distal construction, base/departure rules, RSI,
stochastic failed-break reinforcement, failed-break acceptance, and
90-field namespaced double-slot persistence.

## Backtest evidence

Raw evidence is external under `C:\Users\badaruddinl\.codex\evidence\`.

- `2025-01-01–2026-01-01`: **BLOCKED**. Broker real ticks begin on
  `2025-08-11`; the agent log also reports absent/discarded real ticks and
  price/volume mismatch. Generated ticks are not accepted as replacement.
- `2025-11-01–2026-02-15`: coverage PASS, but no completed trade. The best
  Handgun candidate produced a proximal Sell Limit at `4226.71`, SL `4233.09`,
  and first obstacle `4224.52`, only `0.343R`; it was correctly rejected.
- `2026-06-01–2026-08-24`: coverage PASS, four extreme setups and two M5
  trendline signs, but no complete shakeout/failed-break entry.
- `2026-08-04–2026-08-19`: diagnostic run produced one extreme watch and no
  complete M5-break/shakeout sequence.
- Full `2020-01-01–2026-08-24`: **BLOCKED** by unavailable real-tick history;
  it was not replaced with synthetic ticks.

The strategy detector is causal and active, but its completed sample count is
zero on valid frozen windows. Profitability, profit factor, expectancy, mode
attribution, twin-position broker lifecycle, and drawdown acceptance therefore
cannot pass.

## Release decision

Status: **NOT A RELEASE CANDIDATE**.

The source and test harness are retained as an engineering implementation.
No further threshold tuning was performed on the August evidence window.
DEMO/REAL deployment remains prohibited until new full-quality market data and
a new explicit validation instruction are provided.
