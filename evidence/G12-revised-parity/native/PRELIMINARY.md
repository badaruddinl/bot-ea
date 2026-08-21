# Preliminary Native GOLDm Run

The `goldm-strategy-tester.*` files capture the first native GOLDm Strategy
Tester run at 2026-08-21 07:54 server-terminal log time. It proved the original
five decision vectors only:

- BUY range;
- SELL range;
- no setup;
- sub-one-R obstacle;
- momentum.

The harness was subsequently expanded with setup acceptance, reinforcement,
restart restore, consumed no-resurrection, expiry, and opposite-cancellation
assertions. Therefore this preliminary run is historical evidence only and
**cannot** satisfy final G12 parity. The current capture verifier intentionally
rejects it because the expanded state/restart marker is absent.

REAL order authority remained **DISABLED** and final balance stayed 100.00 USD.
