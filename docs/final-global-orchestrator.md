# GOLD Global Orchestrator

`GOLD_GLOBAL_ORCHESTRATOR` is the single Telegram polling owner and Windows
watchdog for the two final composite workers:

- `goldi`: `GOLD.i#`, Revised BUY + Bear SELL, signal-only.
- `goldm`: `GOLDm#`, Revised BUY + Bear SELL, real execution with the locked
  aggressive balance tiers.

Both workers remain separate processes and bind to separate MT5 executable
paths/accounts. They only send Telegram messages. The orchestrator alone calls
Telegram `getUpdates`, so polling conflicts cannot occur.

Admin commands:

- `/workers`, `/status`, `/heartbeat`
- `/goldi_on`, `/goldi_off`
- `/goldm_on`, `/goldm_off`
- `/all_on`, `/all_off`

Desired ON/OFF state is persisted and restored after a reboot. Every worker
has a single-instance lock and a health file. The orchestrator reports process
exit, worker error/stale heartbeat, restarts a desired worker, and sends a
scheduled hourly status.

The startup task must run under the same Windows account used to log into both
MT5 terminals. `install-final-orchestrator-task.ps1` requests that Windows
credential interactively and registers a startup task that runs even when the
user is logged off. Do not run MT5 under `SYSTEM`, because its saved account
profile and credential store would be different.

Use `prepare-second-mt5.ps1` once to create a distinct executable directory for
GOLDm. Log into that terminal interactively once, then use
`validate-final-terminals.py` for read-only binding validation. The GOLD.i and
GOLDm workers must never point to the same `terminal64.exe` path.

The shutdown event task is best-effort. A powered-off or network-isolated VM
cannot send Telegram. Guaranteed VM-down detection requires an external
dead-man monitor that watches for missing hourly heartbeats.
