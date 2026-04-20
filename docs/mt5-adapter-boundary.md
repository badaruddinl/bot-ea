# MT5 Adapter Boundary

## Purpose

Keep the core project runnable without MT5 installed, while leaving a clean seam for real terminal integration later.

## Boundary rule

The `core` package should not import the MT5 Python package or terminal APIs directly.

Instead:

- core logic depends on stable snapshot models and adapter interfaces
- MT5-specific calls live behind an adapter
- local development can use a mock provider

## Minimum responsibilities of the real MT5 adapter

- load account snapshot
- load symbol snapshot
- load symbol capability snapshot
- estimate margin
- validate order
- later:
  - place order
  - modify order
  - close position
  - load session maps
  - load calendar/news state

## Minimum responsibilities of the mock adapter

- provide in-memory account and symbol fixtures
- enforce volume min/max/step
- enforce stop-level checks
- simulate margin checks
- expose session/capability state

## Official-design implications from research

- sessions are per symbol, not global
- server time is the canonical clock for session/news handling
- spread, stop level, and freeze level should be refreshed close to send time
- Python integration is terminal-dependent and not a full replacement for event-driven EA logic
- custom symbols are a good later option for replay-style testing inside MT5

## Current repo status

Current modules already aligned with this boundary:

- `src/bot_ea/mt5_adapter.py`
- `src/bot_ea/mt5_snapshots.py`
- `tests/test_mock_mt5_adapter.py`
