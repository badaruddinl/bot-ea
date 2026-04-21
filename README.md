# bot-ea

Research-first workspace for a supervised MetaTrader 5 trading bot with a Python risk engine, MT5 adapter, Codex-backed decision path, SQLite telemetry, websocket transport, and a Qt desktop control panel.

This repository is no longer just a design scaffold. It already includes a runnable desktop app for supervised demo and dry-run testing. It is still not positioned as unattended live-trading software.

## Current product state

Implemented now:

- MT5 integration through the Python `MetaTrader5` bridge
- deterministic risk sizing and execution guards
- Codex CLI probing and decision polling
- SQLite runtime persistence and validation summaries
- local websocket service for GUI-to-runtime transport
- Qt desktop app with multi-page navigation:
  - `Dashboard`
  - `Strategy`
  - `History`
  - `Logs`
  - `Settings`

Current operating posture:

- supervised demo and dry-run testing: supported
- broker preflight and manual order preview: supported
- live order flow: operator-gated
- unattended live trading: not ready

Not implemented yet from the master brief:

- operator/dev mode split beyond the current first-pass startup gate
- dev/mock mode badge and explicit operator/dev mode split
- reconnect overlay and safe-halt account-change review UX
- account-scoped AI workspace, documents, and structured context store
- full close/modify lifecycle management for autonomous position handling

## Preferred desktop launch

Normal operator launch on Windows:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Current expected behavior:

- the Qt app is the primary desktop entrypoint
- the app can manage the local websocket backend itself during normal use
- on startup, the app now uses a first-pass startup gate before unlocking the main workspace
- the current gate checks `service -> MT5 -> Codex`
- `scripts/run-websocket-service.ps1` is still available for debugging or isolated backend work, but it is not the preferred operator flow

Current startup-gate scope:

- implemented now:
  - local service connection
  - MT5 readiness check
  - Codex readiness check
  - workspace unlock only after those checks pass
- not implemented yet:
  - account-change review flow
  - reconnect overlay
  - AI workspace/documents/context validation chain from the master brief

## Recommended operator flow

Follow this order inside the Qt app after the startup gate unlocks the workspace:

1. `Check MT5`
2. `Load Codex`
3. `Preview`
4. `Preflight`
5. `Play Runtime`
6. optional `Enable Live`
7. `Approve` or `Reject` only when a live proposal is pending
8. `Telemetry` for post-run review

Important runtime rule:

- when the runtime is active, manual MT5 actions are intentionally restricted so the GUI does not destabilize the live MT5 IPC session

## Desktop UI surface

The Qt app currently exposes:

- `Dashboard`
  - operator overview, readiness chips, snapshot cards, and summary metrics
- `Strategy`
  - trade setup, capital management, Codex settings, and action buttons
- `History`
  - telemetry reload, validation summaries, and post-run review
- `Logs`
  - runtime feed, events, endpoint state, and latest tick visibility
- `Settings`
  - websocket endpoint, model defaults, polling cadence, and runtime DB summary

The current UI still uses several operator/developer-oriented labels such as `Runtime Dashboard`, `Operator Console`, `Manual Order Envelope`, and `Risk Envelope`. The master brief proposes a more user-facing Indonesian copy pass, but that language overhaul is not fully implemented yet.

## Project structure

Key docs and code:

- [docs/project-handoff.md](D:/luthfi/project/bot-ea/docs/project-handoff.md)
- [docs/progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)
- [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
- [docs/desktop-runtime-runbook.md](D:/luthfi/project/bot-ea/docs/desktop-runtime-runbook.md)
- [docs/sqlite-runtime-schema.md](D:/luthfi/project/bot-ea/docs/sqlite-runtime-schema.md)
- [docs/codex-polling-runtime.md](D:/luthfi/project/bot-ea/docs/codex-polling-runtime.md)
- [src/bot_ea/qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
- [src/bot_ea/websocket_service.py](D:/luthfi/project/bot-ea/src/bot_ea/websocket_service.py)
- [src/bot_ea/desktop_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/desktop_runtime.py)
- [src/bot_ea/codex_cli_engine.py](D:/luthfi/project/bot-ea/src/bot_ea/codex_cli_engine.py)
- [src/bot_ea/mt5_adapter.py](D:/luthfi/project/bot-ea/src/bot_ea/mt5_adapter.py)

Research and design references:

- [research/2026-04-20-market-and-platform-research.md](D:/luthfi/project/bot-ea/research/2026-04-20-market-and-platform-research.md)
- [research/2026-04-20-stage-2-deep-research.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-2-deep-research.md)
- [research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md)
- [research/2026-04-20-stage-4-implementation-and-live-research-notes.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-4-implementation-and-live-research-notes.md)
- [research/2026-04-20-stage-5-subagent-integration-notes.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-5-subagent-integration-notes.md)

## Development notes

Useful helper scripts:

- `scripts/run-qt-gui.ps1`
  - launch the Qt desktop app
- `scripts/run-websocket-service.ps1`
  - launch the websocket backend separately for debugging
- `scripts/run-desktop-gui.ps1`
  - legacy Tk launcher kept for backward compatibility and comparison, not the preferred desktop surface now

## Research stance

- official MT5 documentation and broker behavior come first
- strategy recommendations remain provisional until broker-specific demo and backtest validation exist
- small equity accounts must receive explicit warnings, downscaling, and guardrail-driven rejection when a setup is unrealistic
