# bot-ea

Desktop workspace for supervised MetaTrader 5 trading with:

- Python risk sizing and execution guards
- MT5 adapter and broker preflight
- Codex-backed runtime decisions
- SQLite telemetry and validation
- websocket transport
- Qt operator app with dependency gate

This repository is not unattended live-trading software. It is an operator-first desktop runtime with explicit approval and halt behavior.

## Current Product State

Implemented now:

- app-managed local websocket service
- operator-mode startup gate before workspace unlock
- explicit `operator` and `dev / mock` modes
- MT5 readiness chain:
  - service
  - MT5 process
  - MT5 session
  - account fingerprint
  - symbol baseline
- AI readiness chain:
  - runtime command
  - AI workspace
  - AI documents
  - AI context root
  - runtime storage
  - account-scoped resume state
- reconnect overlay and safe halt when MT5 disappears
- account-change review flow with account-scoped context binding
- supervised runtime start/stop, live toggle, approval, rejection, and telemetry review

Still not finished:

- unattended autonomy
- full close/modify lifecycle automation
- packaging/installer distribution
- drift monitoring beyond current telemetry and validation

## Launch

Normal Windows launch:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Operator defaults:

- the Qt app is the main entrypoint
- the app can start the local websocket backend itself
- the main workspace stays locked until the operator dependency gate passes
- the bot runtime does not auto-start after the gate passes

## Modes

### Operator Mode

Rules:

- MT5 is required
- a readable MT5 account is required
- AI runtime is required
- AI workspace/documents/context/storage are required
- the workspace stays locked until all checks pass

### Dev / Mock Mode

Rules:

- bypasses MT5 and AI dependencies
- opens the main workspace for UI tuning and mock testing
- shows a clear `DEV / MOCK MODE` badge

## Startup Gate

Current operator startup sequence:

1. Service lokal
2. MetaTrader 5
3. Sesi MT5
4. Akun aktif
5. Simbol dasar
6. AI runtime
7. Workspace AI
8. Dokumen AI
9. Context / history
10. Storage
11. Resume state
12. Workspace utama

Behavior:

- if any step fails, the app stays on the gate
- the gate shows human-readable status instead of popup spam
- the operator can retry manually or switch to dev mode

## MT5 Disconnect And Account Change

### MT5 lost while idle

- trading controls are disabled
- reconnect overlay is shown
- telemetry and diagnostics remain accessible
- the app keeps retrying MT5 checks from the workspace

### MT5 lost while runtime is active

- runtime enters safe halt
- live mode is disabled
- pending approval is cleared
- operator must reconnect MT5 and start the bot manually again

### Account fingerprint changed

- the app blocks trading controls
- an account review card is shown
- the operator can bind the existing context or create a fresh account context
- runtime must be started manually again after review

## AI Runtime Layout

The desktop app now treats AI runtime readiness as more than a single executable.

Recommended folders:

```text
bot-ea/
  ai_workspace/
  ai_documents/
  ai_context/
  runtime_data/
```

Persisted data now includes:

- `runtime_data/runtime_settings.json`
- `runtime_data/app_settings.json`
- `runtime_data/account_context_map.json`
- `runtime_data/runtime_state.json`

Account contexts are created under `ai_context/<broker>_<server>_<login>/` with:

- `profile.yaml`
- `memory/latest_summary.md`
- `memory/open_issues.md`
- `memory/last_session.json`
- `resume/resume_prompt.md`
- `documents/broker_notes.md`
- `documents/operator_notes.md`

## Operator Flow

Recommended supervised flow:

1. Open MT5 and log into the correct account.
2. Launch the Qt app.
3. Let the startup gate validate dependencies.
4. Review `Strategi`.
5. Click `Refresh Data`.
6. Click `Cek Safety`.
7. Click `Mulai Bot`.
8. Optionally click `Aktifkan Live`.
9. Approve or reject only when a live proposal is pending.
10. Review telemetry in `Riwayat` and `Log`.

Important runtime rule:

- the bot runtime never auto-starts just because the app launches
- live mode never auto-enables

## Key Files

Docs:

- [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
- [docs/desktop-runtime-runbook.md](D:/luthfi/project/bot-ea/docs/desktop-runtime-runbook.md)
- [docs/project-handoff.md](D:/luthfi/project/bot-ea/docs/project-handoff.md)
- [docs/progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)

Code:

- [src/bot_ea/qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
- [src/bot_ea/websocket_service.py](D:/luthfi/project/bot-ea/src/bot_ea/websocket_service.py)
- [src/bot_ea/desktop_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/desktop_runtime.py)
- [src/bot_ea/operator_state.py](D:/luthfi/project/bot-ea/src/bot_ea/operator_state.py)
- [src/bot_ea/mt5_adapter.py](D:/luthfi/project/bot-ea/src/bot_ea/mt5_adapter.py)
