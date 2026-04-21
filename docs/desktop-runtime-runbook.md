# Desktop Runtime Runbook

## Purpose

This runbook describes the current Qt desktop runtime for `bot-ea`.

It is intended for:

- developers maintaining the desktop/runtime stack
- operators running supervised MT5 demo or dry-run sessions

## Operating Posture

Supported now:

- supervised desktop operation
- operator-gated live flow
- MT5 reconnect protection
- account-change review
- account-scoped AI context preparation

Not supported now:

- unattended autonomy
- installer-grade packaging
- full close/modify lifecycle automation

## Desktop Architecture

Primary components:

1. `src/bot_ea/qt_app.py`
2. `src/bot_ea/websocket_service.py`
3. `src/bot_ea/desktop_runtime.py`
4. `src/bot_ea/operator_state.py`
5. `src/bot_ea/mt5_adapter.py`
6. `src/bot_ea/runtime_store.py`

Runtime model:

- the Qt app is the main desktop surface
- the app may start the local websocket backend itself
- backend commands expose readiness probes, manual execution helpers, runtime control, and telemetry
- operator state is persisted under `runtime_data/`

## Launch Model

Preferred launch:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Debug-only backend launch:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-websocket-service.ps1
```

## Startup Gate Contract

Operator mode currently checks:

1. `probe_service_ready`
2. `probe_mt5_process`
3. `probe_mt5_session`
4. `probe_account_fingerprint`
5. `probe_symbol_baseline`
6. `probe_ai_runtime`
7. `probe_ai_workspace`
8. `probe_ai_documents`
9. `probe_ai_context_store`
10. `validate_storage`
11. `build_resume_state`

Only after those pass does the app unlock the main workspace.

Dev mode:

- bypasses the operator gate
- unlocks the workspace directly
- sets the UI badge to `DEV / MOCK MODE`

## Backend Command Surface

Current command surface includes:

- `probe_service_ready`
- `load_runtime_settings`
- `save_runtime_settings`
- `probe_mt5_process`
- `probe_mt5_session`
- `probe_account_fingerprint`
- `probe_symbol_baseline`
- `probe_ai_runtime`
- `probe_ai_workspace`
- `probe_ai_documents`
- `probe_ai_context_store`
- `validate_storage`
- `build_resume_state`
- `refresh_manual`
- `preflight_manual`
- `execute_manual`
- `start_runtime`
- `stop_runtime`
- `set_live_enabled`
- `approve_pending`
- `reject_pending`
- `load_telemetry`

## Operator State Persistence

Files created under `runtime_data/`:

- `runtime_settings.json`
- `app_settings.json`
- `account_context_map.json`
- `runtime_state.json`

Account contexts are created under `ai_context/<broker>_<server>_<login>/`.

Generated files include:

- `profile.yaml`
- `memory/latest_summary.md`
- `memory/open_issues.md`
- `memory/last_session.json`
- `resume/resume_prompt.md`
- `documents/broker_notes.md`
- `documents/operator_notes.md`

Persistence roles:

- `runtime_state.json`: cross-session operator snapshot for the last active account/context, run id, runtime state, shutdown reason, and backend-written runtime metadata
- `memory/last_session.json`: per-account continuity record written by backend lifecycle events
- `resume/resume_prompt.md`: reusable prompt scaffold for the account context; it survives restart but does not auto-start the runtime

## Runtime Lifecycle

### Normal supervised start

1. startup gate passes
2. operator clicks `Mulai Bot`
3. backend starts a runtime thread
4. `run_id` is created
5. runtime events stream back through websocket
6. telemetry is written to SQLite

### MT5 disconnect while idle

- UI shows reconnect overlay
- trade controls are disabled
- logs/history/settings remain accessible
- periodic MT5 checks continue

### MT5 disconnect while runtime is active

- runtime enters safe halt
- live mode is disabled
- pending approval is cleared
- operator must reconnect MT5 and start the bot manually again

Continuity contract after this halt:

- preserved: `runtime_state.json` keeps the active account fingerprint, mapped context, `last_run_id`, `last_runtime_state=halted`, and `last_shutdown_reason`
- preserved: the bound account context keeps `memory/last_session.json`, `resume/resume_prompt.md`, profile, summaries, issues, and notes
- discarded: the in-memory runtime thread, live-enabled state as an active control flag, pending approval payload, and any armed approval key
- restart rule: the operator must pass readiness again as needed and explicitly click `Mulai Bot`; live remains off until re-enabled manually

### Account fingerprint change

- UI opens the account review card
- trade controls remain blocked
- operator may reuse the mapped context or create a new one
- runtime is not restarted automatically

Continuity contract after account review:

- preserved: the previous account context remains on disk unchanged
- preserved: when review is accepted, the selected or newly created context is stored as the mapping for the new fingerprint
- preserved: the chosen context keeps its `resume_prompt.md`, `last_session.json`, summaries, issues, and notes for the next supervised run
- discarded: the old active runtime session does not carry over to the new account, and any pending approval/live state from the interrupted run stays cleared
- restart rule: after review acceptance, the app returns to the readiness flow and the operator must start a new runtime manually

## Readiness Semantics

### MT5

Healthy means:

- terminal can be reached
- session is readable
- account fingerprint is stable
- symbol baseline is readable

### AI Runtime

Healthy means:

- runtime command is callable
- workspace path exists
- documents path exists
- context root exists and is writable
- resume state can be bound for the active MT5 account

### Storage

Healthy means:

- runtime DB path can be created
- runtime metadata can be written

## SQLite Telemetry

Telemetry remains in `runtime_store.py` and covers:

- runs
- polling cycles
- market snapshots
- AI decisions
- risk guard events
- execution events
- position events
- stop events
- runtime logs

## Remaining Gaps

Still pending after this implementation pass:

- autonomous lifecycle management for close/modify
- richer drift monitoring and unattended recovery policies
- packaged desktop distribution
- deeper AI prompt wiring beyond current readiness/context persistence

## Related Files

- [README.md](D:/luthfi/project/bot-ea/README.md)
- [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
- [docs/project-handoff.md](D:/luthfi/project/bot-ea/docs/project-handoff.md)
- [src/bot_ea/qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
- [src/bot_ea/operator_state.py](D:/luthfi/project/bot-ea/src/bot_ea/operator_state.py)
