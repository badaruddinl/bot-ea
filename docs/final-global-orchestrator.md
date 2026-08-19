# GOLD Global Orchestrator

`GOLD_GLOBAL_ORCHESTRATOR` is the single Telegram polling owner and Windows
watchdog for the two final composite workers:

- `goldi`: `GOLD.i#`, Revised BUY + Bear SELL, demo execution with adaptive
  `0.01` below USD 100 and `0.02` from USD 100.
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
- `/pending`, `/subscribers`
- `/approve ID`, `/deny ID`, `/remove ID`

Public users can request GOLD.i notifications with `/start`, inspect access with
`/subscription`, and unsubscribe with `/stop`. Approved users receive only
GOLD.i signal/entry/close lifecycle notifications. GOLDm notifications and all
worker health/control messages are always admin-only; the subscriber registry
is never consulted by GOLDm.

Every signal, executed entry, and close notification identifies the instrument,
signal/order/deal/position IDs where applicable, broker-server time, and VM
local time with its timezone. GOLD.i demo and GOLDm real use separate MT5
executables and separate account bindings.

Both composite workers maintain their preparation/WATCH lifecycle internally
from closed causal bars. WATCH never calls the order API and is not sent to
Telegram. Telegram receives one human-readable final entry/order result and the
later close result only. Approved GOLD.i subscribers receive those final GOLD.i
messages; GOLDm remains admin-only.

Runtime WATCH state is overwritten in the bounded state JSON rather than
appended. Worker and orchestrator JSONL audits rotate at 5 MiB with three
backups, limiting each audit family to approximately 20 MiB.

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
