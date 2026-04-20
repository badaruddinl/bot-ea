# SQLite Runtime Schema

## Purpose

Use SQLite as the local source of truth for a Codex-driven polling runtime.

This replaces the idea of a JSON-only decision contract with a persistent local runtime store that can track:

- runs
- polling cycles
- market snapshots
- AI decisions
- risk-guard outcomes
- execution events
- stop conditions
- logs

## Core tables

- `runs`
  - one row per trading runtime session
- `polling_cycles`
  - one row per poll iteration
- `market_snapshots`
  - summarized market/account state sent into the decision flow
- `ai_decisions`
  - Codex/AI intent per cycle
- `risk_guard_events`
  - deterministic allow/reject outcome after AI proposes an action
- `execution_events`
  - broker-side or mock execution traces
- `position_events`
  - position lifecycle events
- `stop_events`
  - reasons the runtime halted or paused
- `runtime_logs`
  - general operational logs

## Why SQLite here

- easy to carry across hosts
- easy to inspect manually
- no separate server required
- good fit for one-runtime-per-host orchestration

## Current implementation

- `src/bot_ea/runtime_store.py`
