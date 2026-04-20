# Desktop Runtime Runbook

## Purpose

This document is the operational runbook for the Windows desktop GUI in `bot-ea`.

It is written for:

- developers extending the desktop runtime
- operators running supervised MT5 demo tests

This is not a claim that the project is ready for unattended live trading.

Current operating posture:

- `supervised dev test only`
- `dry-run` and broker preflight are supported
- live order submission must remain operator-gated

## System Overview

The desktop app is a control plane around the existing runtime modules:

1. GUI loads runtime parameters.
2. GUI checks `MetaTrader 5` readiness.
3. GUI checks `codex-cli` readiness.
4. GUI starts a background polling runtime.
5. Background runtime pulls MT5 snapshot data.
6. `codex-cli` produces the decision intent.
7. deterministic risk guard accepts or rejects the intent
8. execution runtime performs broker preflight or dry-run/live execution
9. SQLite stores run, snapshot, decision, risk, and execution telemetry
10. GUI reloads the latest telemetry for operator feedback

Core modules:

- [gui_app.py](D:/luthfi/project/bot-ea/src/bot_ea/gui_app.py)
- [desktop_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/desktop_runtime.py)
- [codex_cli_engine.py](D:/luthfi/project/bot-ea/src/bot_ea/codex_cli_engine.py)
- [mt5_adapter.py](D:/luthfi/project/bot-ea/src/bot_ea/mt5_adapter.py)
- [polling_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/polling_runtime.py)
- [runtime_store.py](D:/luthfi/project/bot-ea/src/bot_ea/runtime_store.py)

## Prerequisites

Before launching the GUI, make sure:

- Python `>= 3.11` is installed
- `MetaTrader5` Python package is installed for live/demo MT5 access
- MT5 terminal is installed and already open
- MT5 is logged into the target broker account
- `codex` is available on `PATH`
- the repo is available locally

Recommended host checks:

```powershell
python --version
python -c "import MetaTrader5 as mt5; print(mt5.__version__)"
codex --version
```

## Dev Launch

The simplest Windows dev launch is:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-desktop-gui.ps1
```

Equivalent manual launch:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m bot_ea.gui_app
```

## Startup State Machine

The intended operator state machine is:

1. `Ready`
2. `MT5 unchecked`
3. `codex-cli unchecked`
4. `MT5 ready`
5. `codex-cli ready`
6. `Background runtime starting`
7. `desktop runtime started`
8. `runtime_cycle` feedback repeats
9. optional `Enable Live` if the terminal and account allow it
10. `desktop runtime stopped` or `desktop runtime halted by stop policy`

## One-Click Readiness Contract

### Check MT5

The GUI should confirm:

- terminal connection exists
- account information can be read
- symbol snapshot can be read
- symbol tick can be read
- spread/equity/free margin are visible

Important fields to inspect:

- `connected`
- `terminal_trade_allowed`
- `account_trade_allowed`
- `account_trade_expert`
- `symbol_trade_allowed`

Interpretation:

- if `terminal_trade_allowed=False`, the runtime can still run in dry-run mode
- if MT5 is connected but trading is blocked, `Enable Live` should stay rejected

### Load Codex

The GUI should confirm:

- `codex --version` succeeds
- the selected `codex` executable is callable
- optional model/cwd values are readable

This does not prove that every future decision request will succeed, but it proves the CLI is available.

## Background Runtime Lifecycle

When `Play Runtime` is pressed:

1. the GUI probes `codex-cli`
2. the GUI probes MT5
3. a `run_id` is created
4. SQLite run metadata is initialized
5. a background thread starts `PollingRuntime`
6. each cycle writes:
   - market snapshot
   - AI decision
   - risk guard event
   - execution events
7. GUI polls runtime events and refreshes telemetry

The runtime may stop for:

- operator stop
- stop policy halt
- runtime error

## GUI Surface Map

### Readiness

Top readiness indicators:

- MT5 status
- codex-cli status
- background runtime status

### Runtime controls

Main control buttons:

- `Check MT5`
- `Load Codex`
- `Play Runtime`
- `Stop Runtime`
- `Enable Live` / `Disable Live`
- `Approve Pending`
- `Reject Pending`

### Manual controls

These remain useful for supervised testing:

- `Refresh`
- `Preflight`
- `Execute`
- `Load Telemetry`

## Safe Dev Test Sequence

Use this exact order:

1. open MT5 and log into demo
2. launch the GUI
3. press `Check MT5`
4. confirm connection and symbol quote visibility
5. press `Load Codex`
6. confirm `codex-cli` version appears
7. keep `Allow Live Orders` disabled
8. press `Play Runtime`
9. wait for at least one background cycle
10. press `Load Telemetry`
11. inspect run state, execution health, recent execution events, and rejections

Expected safe result:

- runtime starts
- at least one cycle is stored
- execution remains `DRY_RUN_OK` unless live is explicitly enabled and MT5 allows trading

## Supervised Approval Flow

When live mode is enabled, the runtime still does not send orders immediately.

The runtime now follows:

1. Codex proposes the action
2. deterministic risk guard evaluates it
3. broker preflight evaluates it
4. GUI receives `approval_pending`
5. operator chooses:
   - `Approve Pending`
   - `Reject Pending`
6. only the next matching cycle may submit the approved live order

Important behavior:

- approval is not unattended autonomy
- approval is tied to the matching proposal signature
- if the proposal changes, it should be reviewed again
- if live mode is disabled, execution returns to `dry-run`

## Example Dev Output

Typical dry-run smoke characteristics:

- `status=RUNNING` on the run
- `last_action` present after at least one cycle
- execution ladder similar to:
  - `READY`
  - `PRECHECK_OK`
  - `DRY_RUN_OK`

## Operator Feedback Checklist

The operator should always inspect:

- `run_id`
- `status`
- `last_cycle`
- `last_action`
- `stop_reason`
- `reject_rate`
- latest risk guard allowance/rejection
- latest execution attempt status
- whether the app is in `dry-run` or `live`
- whether there is a pending approval waiting for operator action

## Why Autonomous Live Trading Is Not Ready

The system is not yet ready for unattended live trading because:

- execution runtime still focuses on `OPEN` flow
- close/modify lifecycle is not complete enough for autonomous position management
- realized cost telemetry is still incomplete
- telemetry coverage can still be partial
- operator-facing safety feedback is improving, but not yet sufficient for unsupervised deployment

This means:

- supervised demo tests are valid
- broker preflight tests are valid
- unattended live order management is not yet valid

## Troubleshooting

### MT5 probe fails

Check:

- terminal is open
- broker session is connected
- Python can import `MetaTrader5`
- symbol name is valid for the broker

### codex-cli probe fails

Check:

- `codex` exists on `PATH`
- the selected executable path is correct
- the chosen working directory exists

### Runtime starts but does not produce useful events

Check:

- `poll_interval_seconds`
- runtime DB path
- `codex-cli` output and timeouts
- MT5 symbol quotes and account permissions

### Enable Live is rejected

This usually means one of:

- `terminal_trade_allowed=False`
- account trading is blocked
- MT5 trade API is disabled

## Related Documents

- [codex-polling-runtime.md](D:/luthfi/project/bot-ea/docs/codex-polling-runtime.md)
- [live-mt5-python-integration-notes.md](D:/luthfi/project/bot-ea/docs/live-mt5-python-integration-notes.md)
- [sqlite-runtime-schema.md](D:/luthfi/project/bot-ea/docs/sqlite-runtime-schema.md)
- [progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)
