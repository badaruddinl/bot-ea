# Final GOLD.i / GOLDm composite workers

## Topology

Two Python worker processes run two composite portfolios. Each portfolio runs
the existing `goldm_revised` BUY component and `goldm_bear` SELL component as a
single unit with shared state and, where applicable, shared balance sizing.

```text
GOLD.i worker (signal_only)       GOLDm worker (real)
├─ Revised BUY                    ├─ Revised BUY
├─ Bear SELL                      ├─ Bear SELL
├─ Telegram sender only           ├─ shared Aggressive sizing
└─ no order API                   ├─ MT5 order_check/order_send
                                  └─ Telegram lifecycle sender
```

GOLD.i configuration is pinned to tag
`goldi-profit-v1-research-20260819` and commit `cd609e0`. The worker verifies
SHA-256 hashes of the tagged config files before starting. GOLDm lives only
under `config/final/goldm` and does not modify GOLD.i source/config.

## Files

Each group contains `revised.json`, `bear.json`, `portfolio.json`, and
`worker.json` under `config/final/<group>/`. The shared implementation is under
`src/gold_portfolio/`. The worker never calls Telegram `getUpdates`; both are
one-way senders and the existing production poller remains the only poller.

## Signal and order lifecycle

No promotion, approval, or fallback validation is performed. Engine
`ENTRY_READY` is immediately formatted and sent. GOLD.i stops there. GOLDm
selects one lot from the shared realized balance tiers, performs MT5
`order_check`, revalidates account identity as the final read, and calls
`order_send`.

When a managed position closes, the worker queries MT5 history by position ID
and sends: component decision/reason, entry/close, SL/TP, volume, total P/L
including swap/commission/fee, planned R:R, realized R, duration, and current
balance/equity. State and deduplication are persisted separately per group.

## Required environment

Set Telegram variables plus distinct MT5 bindings:

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ADMIN_CHAT_IDS=...

GOLDI_MT5_TERMINAL_PATH=...
GOLDI_MT5_LOGIN=...
GOLDI_MT5_SERVER=...

GOLDM_REAL_MT5_TERMINAL_PATH=...
GOLDM_REAL_MT5_LOGIN=391425346
GOLDM_REAL_MT5_SERVER=XMGlobal-MT5 14
```

Both terminals must be open. The GOLDm terminal must have Algo Trading enabled;
the real worker refuses to start otherwise. GOLD.i is signal-only but still
requires exact path/login/server binding so it cannot read the GOLDm terminal.

## Launch

- `check-final-goldi-worker.bat` / `check-final-goldm-worker.bat`: one cycle.
- `run-final-goldi-worker.bat` / `run-final-goldm-worker.bat`: foreground.
- `start-final-workers.bat`, `stop-final-workers.bat`, and
  `status-final-workers.bat`: hidden background processes when both terminals
  are installed on the same Windows host.

No EA needs to be attached for these final portfolios; Python connects to the
specified MT5 terminal IPC directly. `GoldMSniperParity` and
`GoldMHighRiskMicroScalper` are not modified or used by this composite worker.
