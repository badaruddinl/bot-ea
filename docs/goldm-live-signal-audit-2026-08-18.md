# GOLDM live signal audit — 2026-08-18

Baseline: `4789a10b8b665f5611809edbed3e4ef66a0da557`

## Confirmed observations

1. The signal promoted around 2026-08-18 14:03 local time followed the predicted
   direction, but the model outcome closed early. This must be investigated as an
   exit-management issue, separately from target selection.
2. The signal promoted around 2026-08-18 17:30 local time used an objective target
   beyond the nearest safe resistance/psychological area. This must be investigated
   as a first-obstacle/room-to-target issue, separately from early exit.
3. `NearestObjectiveTarget` already scans W1/D1 levels, M15/H1 swings, Fibonacci
   extensions, and a psychological step. However, `AddTargetCandidate` discards
   obstacles that do not already satisfy the minimum reward. Consequently, a nearby
   resistance for BUY or nearby support for SELL can disappear from the room check
   while a farther target is selected.
4. After `CompleteSignal`, the current model does not continue counterfactual tracking
   to record whether the original TP or SL would have been reached later. Add shadow
   post-exit MFE/MAE and would-hit-TP/SL evidence before changing the exit policy.

## Required directional level semantics

- BUY: support/retest/invalidation behind the entry; resistance and psychological
  obstacles ahead of the entry.
- SELL: resistance/retest/invalidation behind the entry; support and psychological
  obstacles ahead of the entry.
- A breakout-retest BUY should break resistance and retest it as support. A
  breakout-retest SELL should break support and retest it as resistance.

## Execution observation

The MQL5 EA emits `autoEntryEligible=true` signals but does not submit broker orders.
Broker entry is owned by the Python trade lifecycle. When runtime execution mode is
`off`, an eligible signal is recorded as `READY_MANUAL`; only runtime mode `demo`
may proceed to `OPEN_PENDING`, subject to account binding and broker preflight gates.

Telegram evidence inspected at 2026-08-18 18:36 WIB shows two independent blockers:

1. Every inspected `ENTRY READY` event was enriched as `PRECHECK REJECTED` with
   `event account binding tidak terverifikasi; broker entry diblokir`.
2. The account-context provider reported
   `MT5 account_info() failed: (-10001, 'IPC send failed')`, so the worker could not
   prove that the connected terminal matched the immutable demo-account binding.
3. The control panel subsequently showed `Auto-entry: OFF`, and Telegram confirmed
   `Auto-entry dimatikan. Monitoring dan notifikasi tetap berjalan.`

Turning demo entry on is therefore insufficient until the MT5 IPC/account-context
failure is repaired and the account binding can be verified again.

No production setting was changed during this audit.
