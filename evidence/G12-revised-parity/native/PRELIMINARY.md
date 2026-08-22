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

Raw tester and compile logs are stored outside Git at:

`E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G12-revised-parity\preliminary`

REAL order authority remained **DISABLED** and final balance stayed 100.00 USD.
