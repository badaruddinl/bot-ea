# GoldM Windows VM deployment

## What remains manual on a new host

Install these components before running repository scripts:

1. Git for Windows.
2. Python 3.11 or newer, including `py.exe`, `pip`, and `pythonw.exe`.
3. MetaTrader 5 and MetaEditor.
4. Log in to the intended MT5 account manually. Do not place MT5 passwords in Telegram or Git.
5. Clone this repository and create `.env` from `.env.example`.

At minimum, `.env` must contain `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_IDS`, and
`GOLDM_TRADE_LIFECYCLE_ENABLED=true`. Keep the initial execution mode `off`.

## First installation

Run PowerShell as Administrator from the repository:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\bootstrap-goldm-windows-vm.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-goldm-windows-vm.ps1 -RestartTerminal -TelegramSmokeTest
```

On a new terminal profile, open `GOLD.i#` M15, attach `GoldMSniperParity`, enable Algo
Trading, and save the profile. This one-time UI step is intentionally manual because MT5
does not provide a safe supported interface for selecting a chart and attaching an EA.

## Normal update

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\deploy-goldm-windows-vm.ps1 -RestartTerminal
```

The deployment performs a fast-forward Git pull, installs Python plus the MT5 library,
runs the critical tests, compiles the EA with zero errors and zero warnings, backs up the
database/config/active EA, deploys the EA, and restarts the worker. Add
`-TelegramSmokeTest` when a Telegram diagnostic message is desired.

## Telegram administration

Only chat IDs in `TELEGRAM_ADMIN_CHAT_IDS` can mutate runtime trading configuration.
The default Telegram command menu contains only `/start`, `/status`, `/signal`,
`/history`, and `/stop`. Telegram publishes the extended control menu with a per-chat
scope only for configured root admins. The worker enforces the same allowlist server-side,
so manually typing a hidden admin command does not bypass it.

Approved subscribers remain view-only. Use `/control` for the button panel, `/account`
for the connected MT5 fingerprint, and `/users`, `/pending`, `/approve`, and `/reject`
for notification access. `/users` includes revoke buttons and `/pending` includes approve
and reject buttons, so normal subscriber management does not require typing chat IDs.

Changing DEMO/REAL mode or risk requires a second confirmation within two minutes. The
confirmation is rejected if the MT5 login, server, or account type changed meanwhile.
`Matikan Entry` is deliberately immediate. Telegram never reads or stores an MT5 password.

Changing the actual MT5 login remains a terminal operation: log in to the desired account
in MT5, open `/account` to verify its fingerprint, then use `Kunci Akun Ini` or activate
the matching DEMO/REAL mode and complete the second confirmation. The bot will reject
entry when the connected login/server/type differs from the approved binding.

Execution notifications carry an account scope. Events belonging to `live` are forced to
the root-admin audience, including position ticket, lot, entry/exit, close reason, and P/L.
Public `/signal` and `/history` queries exclude those events as a second privacy boundary.

## Two-terminal DEMO and REAL topology

Running DEMO and REAL continuously is possible, but do not start two copies of the current
all-in-one worker against one bot token and one database. Only one process may poll Telegram
`getUpdates`, and MetaTrader5 terminal connections must be isolated per operating-system
process.

The production topology must use:

1. one Telegram coordinator that owns commands, approvals, and bot polling;
2. one DEMO executor process pinned to its own MT5 installation path, login/server, database
   namespace, and magic number;
3. one REAL executor process pinned to a second MT5 installation path, login/server, database
   namespace, and a different magic number;
4. DEMO events routed to all approved users and REAL events routed only to root admins.

Install the second MT5 terminal and log in manually. Never copy an MT5 password into Git,
Telegram, deployment arguments, or logs. Keep the REAL executor disabled until the separate
executor services, account pins, consent gate, and rollback checks are installed and verified.

Telegram buttons control runtime operations (viewer approval, execution mode, active
account binding, and risk preset). Changes to trading algorithms, message parsing, or
entry/close logic are code releases and must pass the deployment verification pipeline.

## Manual recovery

Each deployment stores a timestamped backup under `runtime_data\deploy-backups`. If an EA
compile fails, the deployment restores the previous active MQ5/EX5 automatically and
starts the worker again. To recover the database or `.env`, stop the Scheduled Task, copy
the selected backup into the repository, and start the task.
