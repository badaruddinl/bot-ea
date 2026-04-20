# Session Memory Export

Date: 2026-04-20

## Purpose

This file is the practical substitute for exporting the full chat memory to Git.

It does **not** contain the model's hidden internal state.
It **does** contain the decisions, assumptions, architecture choices, and active continuation context needed for another host or future session to continue with nearly the same understanding.

## User intent captured in this session

The user does **not** want a classic fixed-rule EA only.

The target system is:

- an `MT5` trading bot
- with `Codex / AI runtime` as the active decision brain
- using `polling` rather than requiring 24/7 hidden autonomous behavior outside the host
- protected by deterministic risk guardrails
- able to use only a portion of account equity via `allocated capital`
- able to stop trading when it has made or lost "enough" according to policy
- portable to another host through GitHub and documentation

## Core design decisions already made

### 1. Platform direction

- prefer `MT5`
- support future `MQL5 native` or `MQL5 + Python/Codex hybrid`
- current scaffold is Python-first because MT5 is not installed on this host

### 2. Brain vs config

- `Codex runtime` is the decision brain
- `strategy` modules are local decision helpers / deterministic baselines
- `risk_engine` is the capital and exposure brain
- `config` is only settings and limits, not the actual decision brain

### 3. Runtime flow

Target flow:

`MT5 -> snapshot aggregation -> Codex runtime -> risk guard -> execution -> SQLite runtime store`

### 4. Risk stance

- equity-aware sizing is mandatory
- allocated capital is supported
- unrealistic allocations must trigger warnings or rejections
- spread is mandatory as a filter, and for scalping should be part of practical risk logic

### 5. Strategy stance

- current baseline family: `session breakout`
- candlestick patterns are not the primary alpha engine
- candlestick/bar structure is secondary context only

## What exists in the repo now

### Risk and sizing

- allocation-aware risk sizing
- practical minimum allocation guidance
- style-aware practical risk floor
- strict / caution / recommend operating modes

### Strategy and validation

- `session_breakout` baseline scaffold
- validation summary and cost realism helpers

### Runtime

- SQLite runtime store
- stop policy
- Codex polling runtime scaffold
- `codex exec` subprocess decision engine scaffold

### Documentation

- architecture
- handoff
- runtime schema
- polling runtime notes
- brain-vs-config clarification
- allocation guidance

## Important constraints discovered in this session

- MT5 is **not installed** on the current host
- `codex` executable **is available** on the current host
- runtime/store/test scaffold is working locally
- live MT5 integration is **not** implemented yet

## Verified status at export time

- repository clean after latest push
- latest tested runtime scaffold includes:
  - runtime store
  - polling runtime
  - stop policy
  - codex cli engine parse path
- unit test suite passed before this export was added

## Best files to read first on a new host

1. `docs/project-handoff.md`
2. `docs/progress-summary.md`
3. `docs/ea-brain-vs-config.md`
4. `docs/codex-polling-runtime.md`
5. `docs/sqlite-runtime-schema.md`
6. `docs/risk-engine-spec.md`
7. `docs/allocation-guidance.md`
8. `src/bot_ea/`

## Immediate next steps from this exact point

1. Install and connect `MT5` on the new host.
2. Build `real MT5 snapshot aggregator`.
3. Connect `polling_runtime` to:
   - real MT5 snapshot provider
   - real execution adapter
   - real Codex runtime invocation
4. Run in `demo` first only.

## Continuation notes for the next agent

- Do not replace the SQLite idea with JSON schema contracts.
- Keep `Codex` as the active decision brain, but never let it bypass deterministic risk guardrails.
- Keep `stop_policy` deterministic for hard limits like profit target, loss limit, drawdown, session timeout, and allocation exhaustion.
- Keep `config` as settings only.
- Prefer intraday polling over per-tick AI decisions.
- If extending to scalping, keep Codex as regime/filter brain and leave micro execution deterministic.
