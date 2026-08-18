# GOLDM_REVISED shadow runtime

`GOLDM_REVISED` is a standalone Python signal engine. It is not the production
`GoldMSniperParity` EA and does not import `goldm_signal` or `goldm_bear`.

## Safety boundary

- MT5 access is read-only: closed bars, symbol metadata, and account context.
- No order, deal, position, or polling API is called.
- BUY decisions are eligible for admin-only shadow notifications.
- SELL decisions are persisted as `observation_only` and are not notified during
  the BUY-first validation phase.
- Storage is isolated at `runtime_data/goldm_revised_shadow.db` and
  `runtime_data/goldm_revised_shadow.jsonl`.
- The existing `goldm telegram worker` Scheduled Task is not referenced.

## Local smoke run

```powershell
python scripts/run-goldm-revised-shadow.py --once `
  --config config/goldm-revised-shadow.json
```

Use `--once` for a read-only snapshot and decision. Omit it for the polling
loop. The runtime uses closed M1 bars and retries MT5 IPC reads with exponential
backoff; an IPC failure records `REVISED_HEALTH=ERROR` and never restarts the
terminal.

## Diagnostic replay

Run a causal broker-bar replay without starting the shadow task:

```powershell
python scripts/run-goldm-revised-replay.py `
  --from-server-time 2026-08-04 `
  --to-server-time 2026-08-19 `
  --server-utc-offset-minutes 180 `
  --output data/research/goldm_revised/replay_20260804_18.json
```

The replay excludes incomplete M1/M5/H1/D1 bars, persists M5 setup state for at
most twelve closed M1 bars, prevents duplicate promotions from one trigger, and
tracks TP/SL/MFE/MAE in R.

## Telegram configuration

The one-way sender reads credentials only from process environment variables:

- `GOLDM_REVISED_TELEGRAM_BOT_TOKEN`
- `GOLDM_REVISED_TELEGRAM_ADMIN_CHAT_IDS` (comma-separated IDs)

It calls only Telegram `sendMessage`. It never calls `getUpdates`, so the
production worker remains the sole owner of Telegram polling.

## Scheduled Task scripts

Register a separate disabled task first:

```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts/register-goldm-revised-shadow.ps1
```

Then use the dedicated `enable-goldm-revised-shadow.bat`,
`disable-goldm-revised-shadow.bat`, and
`status-goldm-revised-shadow.bat`. Registration is not performed automatically
by the repository or by the test suite.

## Promotion gate

The engine is not eligible to replace production until it has at least 20
resolved BUY observations over 10 trading days, positive expectancy better than
the same-window baseline, maximum drawdown no worse than baseline and no more
than 4R, zero fallback promotions, zero first-obstacle violations, no timestamp
look-ahead, and no MT5 IPC degradation. SELL remains observation-only until the
separate `goldm_bear` backtest phase is explicitly started.
