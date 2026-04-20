# Resume Prompt

Use this prompt on a new host if you want another Codex session to resume from nearly the same context:

```text
Read these files first and treat them as the current project memory:

1. docs/project-handoff.md
2. docs/progress-summary.md
3. docs/session-memory-export.md
4. docs/ea-brain-vs-config.md
5. docs/codex-polling-runtime.md
6. docs/sqlite-runtime-schema.md
7. docs/risk-engine-spec.md
8. docs/allocation-guidance.md

Project goal:
- MT5 trading bot
- Codex runtime as active decision brain
- SQLite runtime store
- deterministic risk guard and execution layer
- allocated capital support
- stop trading when policy says enough is enough

Current status:
- Python scaffold exists
- runtime store exists
- stop policy exists
- polling runtime exists
- codex exec connector scaffold exists
- MT5 live integration is not built yet

Continue from the point of implementing the real MT5 snapshot aggregator and wiring it into polling_runtime for demo-mode testing.
```
