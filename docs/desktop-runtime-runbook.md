# Desktop Runtime Runbook

## Purpose

This runbook describes the current Windows Qt desktop runtime for `bot-ea`.

It is for:

- developers working on the desktop/runtime stack
- operators running supervised MT5 demo or dry-run tests

This document only describes behavior that exists now. It does not claim the master brief is fully implemented.

## Current operating posture

- supervised dev and demo testing: supported
- broker preflight and dry-run: supported
- live trading: operator-gated
- unattended autonomy: not ready

## Current architecture

The current desktop stack is:

1. `qt_app.py` as the primary desktop entrypoint
2. local websocket transport between GUI and backend
3. `websocket_service.py` as the backend command/event service
4. `desktop_runtime.py` coordinating probes, runtime start/stop, approvals, and telemetry
5. `mt5_adapter.py` for MT5 bridge access
6. `codex_cli_engine.py` for Codex CLI probing and decision parsing
7. `runtime_store.py` for SQLite persistence

Important current product decision:

- the Qt app can manage the local websocket service on behalf of the operator
- `run-websocket-service.ps1` still exists, but it is mainly for debugging and isolated backend work

## Core files

- [qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
- [websocket_service.py](D:/luthfi/project/bot-ea/src/bot_ea/websocket_service.py)
- [desktop_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/desktop_runtime.py)
- [codex_cli_engine.py](D:/luthfi/project/bot-ea/src/bot_ea/codex_cli_engine.py)
- [mt5_adapter.py](D:/luthfi/project/bot-ea/src/bot_ea/mt5_adapter.py)
- [runtime_store.py](D:/luthfi/project/bot-ea/src/bot_ea/runtime_store.py)

## Launch model

Preferred Windows launch:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Debug-only backend launch:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-websocket-service.ps1
```

Current expectation:

- operator flow should start from the Qt app
- backend script should not be required in normal use
- a first-pass startup gate now runs before the main workspace unlocks

## Host prerequisites

Before launching:

- Python `>= 3.11`
- `MetaTrader5` package available
- MT5 terminal installed and open
- broker account logged in
- `codex` available on `PATH`

Recommended checks:

```powershell
python --version
python -c "import MetaTrader5 as mt5; print(mt5.__version__)"
codex --version
```

## Operator flow

Current recommended runtime sequence:

1. launch Qt app
2. startup gate checks:
   - service
   - MT5
   - Codex
3. workspace unlocks after those checks pass
4. `Preview`
5. `Preflight`
6. `Play Runtime`
7. optional `Enable Live`
8. `Approve` or `Reject` if a proposal appears
9. `Telemetry` or open `History` for review

Important:

- runtime does not auto-start just because the app opens
- live mode does not auto-enable
- a pending live proposal still needs operator action

## Startup gate

Current first-pass behavior:

- the app opens a startup gate before the main workspace
- the gate checks `service -> MT5 -> Codex`
- the main workspace remains locked until those three checks succeed

Current scope only:

- service readiness
- MT5 readiness
- Codex readiness

Not included yet:

- reconnect overlay
- account-change review
- AI workspace/documents/context validation chain from the master brief

## Current UI pages

### Dashboard

Purpose:

- operator overview
- readiness chips
- market snapshot
- manual order envelope
- risk envelope
- current run and status hints

### Strategy

Purpose:

- trade setup
- capital management
- Codex inputs
- action buttons

### History

Purpose:

- telemetry reload
- validation inspection
- post-run review

### Logs

Purpose:

- runtime feed
- event log
- endpoint/runtime/tick summary

### Settings

Purpose:

- websocket endpoint summary
- model summary
- polling cadence
- runtime DB summary

## Command surface currently implemented

Commands exposed through the websocket service include:

- `probe_mt5`
- `probe_codex`
- `refresh_manual`
- `preflight_manual`
- `execute_manual`
- `start_runtime`
- `stop_runtime`
- `set_live_enabled`
- `approve_pending`
- `reject_pending`
- `load_telemetry`

This is the current backend contract. The startup gate reuses the existing service, MT5, and Codex checks; broader startup-gate commands proposed in the master brief do not exist yet.

## Readiness semantics

### Service

Healthy means:

- GUI is connected to the websocket backend
- endpoint is reachable

### MT5

`Check MT5` should confirm:

- terminal connection exists
- account data can be read
- symbol snapshot and tick are available
- trade permissions are visible

Key probe fields:

- `connected`
- `terminal_trade_allowed`
- `account_trade_allowed`
- `symbol_trade_allowed`
- `broker_stop_min_points`

### Codex

`Load Codex` should confirm:

- `codex --version` works
- command is callable
- selected model/work folder can be passed

This proves readiness of the CLI path, not quality of future model responses.

## Manual preview and preflight

### Preview

`Preview` uses `refresh_manual` to update:

- latest market snapshot
- normalized manual order envelope
- risk envelope

### Preflight

`Preflight` uses `preflight_manual` to test whether the current setup passes broker/risk checks before a live send.

Expected statuses:

- `PRECHECK_OK`
- `PRECHECK_REJECTED`
- `GUARD_REJECTED`

## Runtime lifecycle

When `Play Runtime` is pressed:

1. GUI sends `start_runtime`
2. backend creates a `run_id`
3. SQLite run metadata is initialized
4. runtime begins polling
5. market snapshot, AI decisions, risk events, and execution events are written
6. GUI receives runtime events through websocket

Expected runtime states:

- `Runtime stopped`
- `Runtime running`
- `NO_TRADE: ...`
- `runtime_error: ...`

Important interpretation:

- `NO_TRADE` means the runtime is still alive and the latest cycle chose not to enter
- it does not mean the runtime necessarily stopped

## Manual actions while runtime is active

Current protective behavior:

- while the runtime is active, some manual MT5 actions are restricted
- this prevents the GUI manual path from colliding with the runtime MT5 path and breaking IPC stability

This guard exists because earlier mixed access produced MT5 IPC failures such as `(-10004, 'No IPC connection')`.

## Live gating and approvals

Current live flow:

1. operator enables live mode manually
2. runtime still runs through guard and broker checks
3. if approval is required, GUI shows pending approval state
4. operator chooses `Approve` or `Reject`

This is supervised. It is not unattended autonomy.

## Current failure classes

### MT5 IPC loss

Example:

- `MT5 account_info() failed: (-10004, 'No IPC connection')`

Meaning:

- backend lost its bridge to MT5

Current handling:

- runtime may halt or report runtime error
- operator should re-validate MT5 and avoid mixed manual/runtime access

### Codex timeout

Example:

- `codex exec timed out after 60 seconds`

Meaning:

- decision call exceeded the configured timeout

Current behavior:

- runtime falls back safely instead of turning that into a live trading action

### Codex contract invalid

Example:

- response missing required keys
- response is meta-text instead of the expected contract

Current behavior:

- parser marks the response invalid
- runtime records an explicit fallback reason in telemetry/DB

## SQLite telemetry

The runtime DB records:

- runs
- polling cycles
- market snapshots
- AI decisions
- risk guard results
- execution events
- runtime logs

Review:

- [sqlite-runtime-schema.md](D:/luthfi/project/bot-ea/docs/sqlite-runtime-schema.md)

## Current limitations

The following are still not implemented even though the master brief proposes them:

- operator/dev mode split with explicit `DEV / MOCK MODE` UI
- reconnect overlay
- account-changed review sheet
- AI runtime workspace/documents/context readiness chain
- account-scoped AI context storage
- automatic close/modify lifecycle management for autonomous trading

## Relationship to the master brief

The master brief is now a roadmap, not a description of shipped behavior.

Safe framing:

- implemented now: Qt pages, websocket-managed desktop runtime, probes, preview, preflight, approvals, telemetry
- roadmap later: startup gate, reconnect/account review UX, AI context ecosystem, stronger accessibility and responsiveness pass

## Related docs

- [README.md](D:/luthfi/project/bot-ea/README.md)
- [user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
- [project-handoff.md](D:/luthfi/project/bot-ea/docs/project-handoff.md)
- [progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)
