# EA Bot Blueprint

## Goal

Build an MT5 trading bot that can:

- choose whether a symbol is appropriate for the user's current equity
- warn when the requested market is too risky
- auto-calculate position size from current equity and stop distance
- downshift into stricter behavior when equity is limited or friction is high
- remain auditable and testable

## Operating modes

### 1. Recommend

- Symbol and account conditions look acceptable
- Bot can use baseline rules

### 2. Caution

- Symbol is tradable but friction or account size is borderline
- Bot reduces size and entry frequency

### 3. Strict

- User insists on trading a risky symbol for the current equity
- Bot applies stronger rules automatically

Strict mode should include:

- lower `risk_pct`
- only one open position per strategy/symbol cluster
- stronger setup threshold
- no trade during high-impact news windows
- tighter spread filter
- cooldown after losses
- hard daily loss shutdown

## Main subsystems

### Risk engine

Responsibilities:

- read account state
- classify instrument suitability
- compute lot size
- estimate margin
- enforce exposure and drawdown caps

### Decision engine

Responsibilities:

- compute setup validity
- attach confidence/quality score
- request execution only if all risk and market filters pass

### Execution engine

Responsibilities:

- normalize volume
- validate request
- send order
- verify retcodes
- record outcome

### Position manager

Responsibilities:

- stop-loss and take-profit management
- break-even and trailing rules
- kill-switch handling

### Telemetry and logs

Record:

- account snapshot
- symbol snapshot
- decision rationale
- trade request
- trade result
- rejection reason

## Suggested first implementation order

1. account and symbol introspection
2. risk engine
3. execution engine
4. one baseline strategy
5. position management
6. logging
7. tuning harness

## Baseline strategy recommendation

Start with one of:

- `session breakout scalp`
- `trend pullback intraday`

Avoid at v1:

- grid
- martingale
- multi-strategy blending
- multi-symbol aggressive scalping

## Tuning workflow

1. Use research to choose initial parameter ranges.
2. Backtest per broker symbol.
3. Evaluate slippage/spread sensitivity.
4. Walk-forward validate.
5. Demo forward test.
6. Freeze a conservative live profile.

## Readiness gate before live trading

The bot should not go live until it has:

- stable connection behavior
- correct lot normalization
- correct margin and risk checks
- consistent session and news filters
- acceptable demo forward-test behavior
- clear kill-switch and recovery behavior
