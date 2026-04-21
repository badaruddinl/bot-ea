# Project Handoff

## Repository State

`bot-ea` is now a supervised MT5 desktop runtime with real operator gating, real persistence, and real recovery state.

This repo is no longer just:

- research
- a risk-engine scaffold
- a loose GUI prototype

It now contains:

- live MT5 probing and broker preflight
- runtime start/stop with telemetry
- websocket transport between GUI and backend
- a Qt operator app
- startup dependency gate
- dev/mock bypass mode
- reconnect handling
- account-change review flow
- account-scoped AI context persistence

## What Works Now

Core capabilities currently implemented:

- `risk_engine`
- `mt5_adapter`
- `desktop_runtime`
- `runtime_store`
- `websocket_service`
- `qt_app`
- `operator_state`

User-facing product behavior currently implemented:

- operator mode blocks workspace access until dependency checks pass
- dev/mock mode can open the workspace without MT5 or AI runtime
- MT5 disconnect triggers reconnect-safe behavior
- MT5 disconnect during runtime forces safe halt
- account fingerprint changes trigger explicit review before trading resumes
- AI runtime readiness includes workspace/documents/context/storage, not only the executable
- account contexts are isolated under `ai_context/`

## Current Entry Point

Primary desktop entry:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

The old backend-first launch story is no longer the main operator narrative.

## Current Operator Flow

1. launch the Qt app
2. let the startup gate validate:
   - service
   - MT5 process
   - MT5 session
   - account fingerprint
   - symbol baseline
   - AI runtime
   - AI workspace
   - AI documents
   - AI context root
   - storage
   - resume state
3. review setup in `Strategi`
4. `Refresh Data`
5. `Cek Safety`
6. `Mulai Bot`
7. optional `Aktifkan Live`
8. `Setujui Proposal` or `Tolak Proposal` when required
9. inspect `Riwayat` and `Log`

The runtime still does not auto-start and live mode still does not auto-enable.

## Important Persistence

Runtime and operator state now persist in:

- `runtime_data/runtime_settings.json`
- `runtime_data/app_settings.json`
- `runtime_data/account_context_map.json`
- `runtime_data/runtime_state.json`

Per-account AI context is created in:

- `ai_context/<broker>_<server>_<login>/`

## Recovery Semantics

### MT5 lost while idle

- reconnect overlay appears
- trading controls are disabled
- telemetry access remains available

### MT5 lost while runtime is active

- runtime safe halt
- live mode disabled
- pending approval cleared

### Account changed

- account review card appears
- operator must accept mapped context or create a new context
- runtime must be started again manually

## What Is Still Missing

The repo is still not a finished autonomous trading product.

Still pending:

- close/modify lifecycle automation
- drift monitoring hardening
- unattended autonomy
- packaging and installer work
- richer AI prompt wiring that consumes all stored context during runtime execution

## Recommended Reading Order

1. [README.md](D:/luthfi/project/bot-ea/README.md)
2. [docs/progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)
3. [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
4. [docs/desktop-runtime-runbook.md](D:/luthfi/project/bot-ea/docs/desktop-runtime-runbook.md)
5. [src/bot_ea/operator_state.py](D:/luthfi/project/bot-ea/src/bot_ea/operator_state.py)
6. [src/bot_ea/qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
7. [src/bot_ea/websocket_service.py](D:/luthfi/project/bot-ea/src/bot_ea/websocket_service.py)
8. [src/bot_ea/desktop_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/desktop_runtime.py)

## Recommended Next Priorities

1. Feed stored account context more deeply into the AI decision prompt path.
2. Extend autonomous lifecycle handling beyond open-only supervision.
3. Add stronger drift and broker anomaly monitoring.
4. Package the desktop app for cleaner operator deployment.
