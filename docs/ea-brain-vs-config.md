# EA Brain vs Config

## Short answer

The `brain` of the EA should live in code modules, not in config.

Config tells the EA:

- what limits apply
- which symbols or styles are allowed
- what thresholds are currently enabled

The brain decides:

- whether a setup is valid
- whether risk is acceptable
- whether execution should proceed

## Practical split

### `config`

Use config for:

- risk percentages
- capital allocation mode and value
- session enable flags
- news-blackout windows
- spread caps
- feature toggles

Config should be data, not trading logic.

### `strategy`

This is the main decision brain for market interpretation.

It should answer:

- buy
- sell
- hold
- stand down

Current repo direction:

- `src/bot_ea/strategies/session_breakout.py`

### `risk_engine`

This is the capital and exposure brain.

It should answer:

- how much capital is actually allocated
- whether that allocation is realistic
- what risk cash budget is allowed
- whether the setup should be rejected for practicality

Current repo direction:

- `src/bot_ea/risk_engine.py`

### `execution_guard` and `mt5_adapter`

These modules do not invent strategy.

They:

- validate broker constraints
- normalize order requests
- estimate margin
- call the terminal or mock adapter

Current repo direction:

- `src/bot_ea/execution_guard.py`
- `src/bot_ea/mt5_adapter.py`
- `src/bot_ea/mt5_snapshots.py`

## Runtime flow when the EA is live

1. EA main loop gets fresh market and account snapshots.
2. Strategy module evaluates the market.
3. Risk engine translates the setup into practical risk and sizing.
4. Execution guard checks broker-side constraints.
5. MT5 adapter sends or rejects the order.
6. Validation and logs record what happened.

## Design mistake to avoid

Do not try to make the whole EA configurable by moving all logic into config.

That usually creates:

- hidden strategy logic in parameter files
- poor testability
- hard-to-debug behavior
- accidental overfitting

The right pattern is:

- code contains the decision logic
- config adjusts the operating profile
