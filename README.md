# bot-ea

Research-first workspace for an autonomous MetaTrader trading bot with strict risk controls.

## Current focus

- Build from research, not from zero
- Prioritize MT5 because its native APIs and Python bridge expose account, symbol, margin, profit, and order validation primitives
- Treat internet research as a baseline only; final tuning must come from broker-specific backtests and demo forward tests

## Proposed stack

- `MT5 native (MQL5)` for execution-critical logic
- `Python + MetaTrader5` for research, tuning, analytics, orchestration, and possible hybrid decision logic
- Risk engine as a first-class subsystem, not an afterthought

## Project structure

- [research/2026-04-20-market-and-platform-research.md](D:\luthfi\project\bot-ea\research\2026-04-20-market-and-platform-research.md)
- [research/2026-04-20-stage-2-deep-research.md](D:\luthfi\project\bot-ea\research\2026-04-20-stage-2-deep-research.md)
- [research/2026-04-20-stage-3-decision-tree-and-candlestick-research.md](D:\luthfi\project\bot-ea\research\2026-04-20-stage-3-decision-tree-and-candlestick-research.md)
- [docs/ea-bot-blueprint.md](D:\luthfi\project\bot-ea\docs\ea-bot-blueprint.md)
- [docs/mt5-validation-protocol.md](D:\luthfi\project\bot-ea\docs\mt5-validation-protocol.md)
- [docs/strategy-candidates.md](D:\luthfi\project\bot-ea\docs\strategy-candidates.md)
- [docs/decision-tree-pseudorules.md](D:\luthfi\project\bot-ea\docs\decision-tree-pseudorules.md)
- [docs/candlestick-patterns-assessment.md](D:\luthfi\project\bot-ea\docs\candlestick-patterns-assessment.md)
- [docs/project-handoff.md](D:\luthfi\project\bot-ea\docs\project-handoff.md)
- [docs/progress-summary.md](D:\luthfi\project\bot-ea\docs\progress-summary.md)
- [config/parameter-map.md](D:\luthfi\project\bot-ea\config\parameter-map.md)

## Research stance

- Facts from official docs are separated from design recommendations
- Any recommendation about strategy quality is provisional until validated on the target broker/account
- Equity-limited users should receive explicit warnings, automatic downscaling, and strict-mode guardrails
