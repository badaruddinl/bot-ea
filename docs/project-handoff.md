# Project Handoff

## What this repository is now

`bot-ea` started as a research-first MT5 trading bot blueprint. It is now further along than that:

- research and design documents are still the foundation
- a Python risk and execution stack exists
- MT5 integration through the Python bridge exists
- a Codex CLI decision path exists
- SQLite runtime persistence exists
- a websocket service exists
- a Qt desktop GUI exists and is now the primary desktop surface

This is still not a finished autonomous trading product. It is a supervised runtime prototype with real plumbing, real telemetry, and real operator controls.

## What is currently implemented

Core subsystems available in the repo now:

- `risk_engine`
  - allocation, sizing, guardrails, and realism warnings
- `mt5_adapter`
  - MT5 account/symbol/tick probing through Python `MetaTrader5`
- `desktop_runtime`
  - probes, runtime start/stop, approvals, and telemetry integration
- `codex_cli_engine`
  - Codex CLI probing, prompting, and decision parsing
- `runtime_store`
  - SQLite persistence for runs, cycles, snapshots, decisions, and events
- `websocket_service`
  - backend transport between runtime and GUI
- `qt_app`
  - multi-page desktop GUI with:
    - `Dashboard`
    - `Strategy`
    - `History`
    - `Logs`
    - `Settings`

## What the product can do now

As of the current main branch, the repository supports:

- MT5 readiness probing
- Codex readiness probing
- manual market preview
- broker/risk preflight
- supervised runtime start/stop
- live-mode toggle with operator gating
- approval/reject flow for pending proposals
- telemetry reload and validation review
- websocket-backed GUI/runtime separation

Normal operator launch is now the Qt app. The backend service can still be launched manually for debugging, but it is no longer the preferred operator-first story.

## What the product is not yet

Still not ready:

- unattended live trading
- full autonomous position lifecycle management
- account-scoped AI workspace/documents/context system from the master brief
- startup dependency gate that blocks the main workspace until all readiness checks pass
- reconnect overlay and account-changed review UX
- packaging/installer-grade desktop distribution

## Current repo narrative

The most accurate reading order is:

1. [README.md](D:/luthfi/project/bot-ea/README.md)
2. [docs/progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)
3. [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
4. [docs/desktop-runtime-runbook.md](D:/luthfi/project/bot-ea/docs/desktop-runtime-runbook.md)
5. [docs/codex-polling-runtime.md](D:/luthfi/project/bot-ea/docs/codex-polling-runtime.md)
6. [docs/sqlite-runtime-schema.md](D:/luthfi/project/bot-ea/docs/sqlite-runtime-schema.md)
7. [src/bot_ea](D:/luthfi/project/bot-ea/src/bot_ea)

Research files remain useful for rationale and future tuning:

1. [research/2026-04-20-market-and-platform-research.md](D:/luthfi/project/bot-ea/research/2026-04-20-market-and-platform-research.md)
2. [research/2026-04-20-stage-2-deep-research.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-2-deep-research.md)
3. [research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md)
4. [research/2026-04-20-stage-4-implementation-and-live-research-notes.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-4-implementation-and-live-research-notes.md)
5. [research/2026-04-20-stage-5-subagent-integration-notes.md](D:/luthfi/project/bot-ea/research/2026-04-20-stage-5-subagent-integration-notes.md)

## What changed since the original research-only state

The old handoff description that said there was no MT5 integration, no live workflow, and no real Codex connector is no longer correct.

What has moved forward:

- live/demo MT5 probing exists
- runtime execution path exists
- SQLite telemetry is real
- Qt GUI is real
- websocket service is real
- supervised live approval flow exists

## Current operator workflow

This is the current intended supervised flow:

1. launch Qt app
2. `Check MT5`
3. `Load Codex`
4. `Preview`
5. `Preflight`
6. `Play Runtime`
7. optional `Enable Live`
8. `Approve` or `Reject` if a proposal is pending
9. review `Telemetry` in `History`

This should not be described as autonomous trading.

## Current limitations that still matter technically

### 1. Runtime and manual MT5 actions must not fight each other

The stack has needed explicit protection so manual GUI actions do not destabilize MT5 IPC while the runtime is already active.

### 2. Codex responses still need defensive handling

The project has already seen:

- Codex timeouts
- contract-invalid responses
- meta-text responses that do not match the expected decision schema

Parser and fallback handling are stronger now, but this remains an active risk area.

### 3. Execution lifecycle is still incomplete for autonomy

The open flow is further along than:

- close lifecycle
- modify lifecycle
- long-running autonomous position management

### 4. UI and docs are still catching up to the master brief

The master brief now acts as a product roadmap. It should not be mistaken for a statement that startup gate, dev mode, reconnect overlay, or account-scoped AI context already exist in code.

## Recommended next implementation priorities

The most defensible next steps remain:

1. continue hardening Codex response and timeout handling
2. finish Qt UX cleanup and document it consistently
3. add startup dependency gate
4. add MT5 reconnect and account-change state handling
5. add account-scoped AI context design if the product is truly moving toward long-lived operator sessions
6. finish close/modify lifecycle capture and broker drift monitoring

## Host setup on another machine

Minimum practical setup:

- Windows host or VPS
- MetaTrader 5 installed
- broker or demo account logged in
- Python 3.11+
- `MetaTrader5` package
- `codex` available on `PATH`
- local copy of the repo

Then launch:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

## Files that matter first

Operational docs:

- [README.md](D:/luthfi/project/bot-ea/README.md)
- [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
- [docs/desktop-runtime-runbook.md](D:/luthfi/project/bot-ea/docs/desktop-runtime-runbook.md)
- [docs/progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)

Runtime code:

- [src/bot_ea/qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
- [src/bot_ea/websocket_service.py](D:/luthfi/project/bot-ea/src/bot_ea/websocket_service.py)
- [src/bot_ea/desktop_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/desktop_runtime.py)
- [src/bot_ea/codex_cli_engine.py](D:/luthfi/project/bot-ea/src/bot_ea/codex_cli_engine.py)
- [src/bot_ea/mt5_adapter.py](D:/luthfi/project/bot-ea/src/bot_ea/mt5_adapter.py)

## Master brief framing

Use the master implementation brief as:

- roadmap
- acceptance target
- UX/product spec for future phases

Do not use it as proof that:

- startup gate exists
- operator/dev mode split exists
- reconnect overlay exists
- account review flow exists
- AI workspace/documents/context persistence exists

Those are still pending implementation work.
