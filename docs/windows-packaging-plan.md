# Windows Packaging Plan

## Decision

Do not build an installer yet.

Current recommendation:

- keep the project in `dev-run` mode
- keep the package installable for editable internal use
- stabilize the desktop runtime workflow first
- package later, only after runtime and operator flow are less volatile

## Packaging Baseline Now

Keep the Python package metadata good enough for internal install and launch, even before any installer work.

Current baseline:

- `pyproject.toml` defines a real build backend for the `src/` layout
- the websocket dependency is declared at package level
- console entry points exist for the current app path:
  - `bot-ea-qt`
  - `bot-ea-websocket`

Recommended local installs:

- `python -m pip install -e .`
  - installs the base package and websocket service dependency
- `python -m pip install -e ".[desktop]"`
  - installs the Qt operator shell
- `python -m pip install -e ".[desktop,live]"`
  - installs the operator shell plus the MT5 Python bridge on machines that already have MT5 available

## Why Installer Work Is Premature

The hardest dependencies in this project are not Python-only:

- `MetaTrader 5` terminal must already exist
- broker login state must already exist
- MT5 account permissions can differ by host
- `codex-cli` must be available and callable

An installer would not solve the core operational risks yet. It would only freeze a runtime contract that is still evolving.

## Minimum Exit Criteria Before Packaging

Packaging becomes reasonable only after these are stable:

1. dev launch is reliable and documented
2. MT5 readiness failures are surfaced cleanly
3. codex-cli background runtime is stable across repeated runs
4. runtime status transitions are clear
5. close/modify lifecycle is implemented well enough for real operator feedback
6. telemetry and validation outputs are trustworthy enough for supervised demo use

## Suggested Order

### Phase 1: Dev Run

Stay here now.

Use:

- `.\scripts\run-qt-gui.ps1`
- `bot-ea-qt`
- `python -m bot_ea.qt_app`

For backend-only debugging:

- `.\scripts\run-websocket-service.ps1`
- `bot-ea-websocket`
- `python -m bot_ea.websocket_service`

Goals:

- developer iteration
- supervised GUI testing
- dry-run/demo verification

### Phase 2: Single-File/Folder Bundle

Only after Phase 1 is stable.

Most likely Windows packaging candidate:

- `PyInstaller`

Why:

- simple path from Python desktop app to executable
- good fit for the Qt operator app
- useful for smoke bundling before a full installer

Deliverable:

- unpacked app folder or single executable for internal testing

### Phase 3: Installer

Only after the bundle behaves predictably.

Likely installer layer:

- `Inno Setup` or equivalent Windows installer wrapper around the bundled app

Goals:

- desktop shortcut
- start menu entry
- predictable install path
- versioned upgrade path

## What To Document Before Packaging

Before any bundling work, the repo should already document:

- how to launch in dev mode
- how to install the editable package and which extras are needed
- what MT5 state must already exist
- what `codex-cli` requirement exists
- what dry-run vs live means
- what operator must inspect before enabling live

## What Not To Promise Yet

Do not present the app as:

- unattended live trading software
- one-click ready on any Windows host
- safe to distribute to non-technical operators without supervised testing

## Current Recommendation

Right now the right path is:

1. keep improving the desktop runtime in dev mode
2. document the exact runbook
3. finish lifecycle/validation/operator feedback gaps
4. create an internal bundle
5. only then consider an installer
