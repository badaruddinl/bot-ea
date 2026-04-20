# bot-ea

Research-first workspace for an autonomous MetaTrader trading bot with strict risk controls.

## Current focus

- Build from research, not from zero
- Prioritize MT5 because its native APIs and Python bridge expose account, symbol, margin, profit, and order validation primitives
- Treat internet research as a baseline only; final tuning must come from broker-specific backtests and demo forward tests
- Build the first testable core as pure Python risk logic, then attach MT5 adapters and execution code on top

## Proposed stack

- `MT5 native (MQL5)` for execution-critical logic
- `Python + MetaTrader5` for research, tuning, analytics, orchestration, and possible hybrid decision logic
- Risk engine as a first-class subsystem, not an afterthought

## Project structure

- [research/2026-04-20-market-and-platform-research.md](D:\luthfi\project\bot-ea\research\2026-04-20-market-and-platform-research.md)
- [research/2026-04-20-stage-2-deep-research.md](D:\luthfi\project\bot-ea\research\2026-04-20-stage-2-deep-research.md)
- [research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md](D:\luthfi\project\bot-ea\research\2026-04-20-stage-3-decision-tree-and-candlestick-research.md)
- [research/2026-04-20-stage-4-implementation-and-live-research-notes.md](D:\luthfi\project\bot-ea\research\2026-04-20-stage-4-implementation-and-live-research-notes.md)
- [research/2026-04-20-stage-5-subagent-integration-notes.md](D:\luthfi\project\bot-ea\research\2026-04-20-stage-5-subagent-integration-notes.md)
- [docs/ea-bot-blueprint.md](D:\luthfi\project\bot-ea\docs\ea-bot-blueprint.md)
- [docs/mt5-validation-protocol.md](D:\luthfi\project\bot-ea\docs\mt5-validation-protocol.md)
- [docs/strategy-candidates.md](D:\luthfi\project\bot-ea\docs\strategy-candidates.md)
- [docs/decision-tree-pseudorules.md](D:\luthfi\project\bot-ea\docs\decision-tree-pseudorules.md)
- [docs/candlestick-patterns-assessment.md](D:\luthfi\project\bot-ea\docs\candlestick-patterns-assessment.md)
- [docs/risk-engine-spec.md](D:\luthfi\project\bot-ea\docs\risk-engine-spec.md)
- [docs/allocation-guidance.md](D:\luthfi\project\bot-ea\docs\allocation-guidance.md)
- [docs/mt5-adapter-boundary.md](D:\luthfi\project\bot-ea\docs\mt5-adapter-boundary.md)
- [docs/ea-brain-vs-config.md](D:\luthfi\project\bot-ea\docs\ea-brain-vs-config.md)
- [docs/session-breakout-v1.md](D:\luthfi\project\bot-ea\docs\session-breakout-v1.md)
- [docs/validation-harness-spec.md](D:\luthfi\project\bot-ea\docs\validation-harness-spec.md)
- [docs/sqlite-runtime-schema.md](D:\luthfi\project\bot-ea\docs\sqlite-runtime-schema.md)
- [docs/codex-polling-runtime.md](D:\luthfi\project\bot-ea\docs\codex-polling-runtime.md)
- [docs/project-handoff.md](D:\luthfi\project\bot-ea\docs\project-handoff.md)
- [docs/progress-summary.md](D:\luthfi\project\bot-ea\docs\progress-summary.md)
- [config/parameter-map.md](D:\luthfi\project\bot-ea\config\parameter-map.md)
- `src/bot_ea/`
  - Python scaffold for risk, execution guards, decision family selection, MT5 adapter seams, strategy baseline, validation summaries, SQLite runtime store, stop policy, and Codex polling runtime
- `tests/test_risk_engine.py`
  - smoke tests for the first risk-engine slice

## Research stance

- Facts from official docs are separated from design recommendations
- Any recommendation about strategy quality is provisional until validated on the target broker/account
- Equity-limited users should receive explicit warnings, automatic downscaling, and strict-mode guardrails
- Candlestick logic is treated as secondary context unless future broker-specific evidence proves otherwise
