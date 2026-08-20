# G03 Common Strategy Contract

Status: **IN_PROGRESS**

Scope: SHARED and CROSS_PROFILE. No Revised/Bear rules are migrated in this gate. REAL authority remains disabled.

## Portable typed contracts

Implemented immutable domain contracts for:

- `Bar`, `Tick`, `Timeframe`, `BarSeries`, and `MarketSnapshot`;
- `StrategyConfig`, `ProfileConfig`, bounded warmup requirements;
- `StrategyState`, `SetupState`, and typed state fields;
- `StrategyDecision`, fully owned `SignalPlan`, and `EngineOutput`;
- `PositionState` and versioned `EngineEvent`.

The state-explicit `PureStrategyEngine` protocol defines:

```text
on_warmup(history)
on_bar_close(state, timeframe, bar)
on_tick(state, tick)
on_position_event(state, event)
```

Each call returns immutable `next_state`, decisions, and events. Output validation enforces exact sequence increments, monotonic semantic time, stable profile/strategy identity, and no cross-profile decision/event ownership.

## Purity and causality

- Market bars and ticks require offset-aware timestamps and cannot be newer than `available_at`.
- Warmup is explicit and bounded by configuration.
- Signal plans carry profile/version, setup/signal identity, setup/entry-ready/expiry times, structural geometry, risk, invalidation, spread/drift/tick contracts, account/server/mode/terminal ownership, and magic.
- The contract module has no MT5, environment, database, Telegram, network, sleep, or order-send dependency.
- No symbol-substring inference exists; `ProfileConfig` is supplied explicitly from the immutable manifest.

## Focused verification

```text
python -m ruff check src/gold_engine_core tests/gold_engine_core
exit=0

python -m mypy --follow-imports=skip src/gold_engine_core
exit=0

python -m pytest -q --basetemp=<external>/G03-common-strategy-contract/pytest-temp-run3 --cov=gold_engine_core --cov-branch --cov-report=term-missing --cov-report=xml:<external>/G03-common-strategy-contract/coverage-run3.xml --cov-fail-under=90 tests/gold_engine_core
exit=0
result=37 passed
branch_coverage=91.91%
coverage_xml_sha256=dcc0a15b9a8ec3d3dfed1f9caffa1f98ddc939edf8fda55e64cb4dadeba9d9f3
```

The first focused run exposed non-finite Decimal exception leakage; the shared validator was corrected and the authoritative rerun passed. Quality-gate E2E and full regression remain required before PASS.
