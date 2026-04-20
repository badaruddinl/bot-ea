# Codex Polling Runtime

## Goal

Run Codex as the active decision engine in a polling loop, while keeping:

- risk veto deterministic
- broker execution deterministic
- persistence local in SQLite

## Runtime flow

1. Start a `run`.
2. Poll market/account/session state from the provider.
3. Persist the summarized snapshot in SQLite.
4. Ask Codex for a decision intent.
5. Persist the AI decision.
6. Run the deterministic risk guard.
7. If accepted, pass the action to execution.
8. Persist execution results.
9. Re-check stop policy and continue or halt.

## Important rule

Codex is the `decision brain`, but not the final bypass authority.

- Codex proposes
- risk guard allows or rejects
- execution layer executes

## Polling suitability

Best fit:

- intraday
- regime-aware decision loops
- session-based trading

Poor fit as pure AI loop:

- sub-second scalping
- very tight stop microstructure trading

## Halt logic

The runtime should stop when deterministic stop policy says enough is enough, such as:

- profit target reached
- loss limit reached
- drawdown limit reached
- too many consecutive losses
- too many trades
- runtime/session time exhausted
- remaining allocation too small

## Current implementation

- `src/bot_ea/polling_runtime.py`
- `src/bot_ea/stop_policy.py`
- `src/bot_ea/runtime_store.py`
- `src/bot_ea/codex_cli_engine.py`
