# GoldM Sniper Confidence Bot v1

This branch introduces a separate, signal-only Python boundary. It intentionally
does not reuse the existing order execution runtime and does not expose an
`order_send` method.

## Broker profile

The active broker symbol is `GOLD.i#` with these supplied facts:

| Field | Value |
| --- | ---: |
| Instrument | GOLD / Precious Metals |
| Contract size | 100 troy ounces per lot |
| Minimum / maximum volume | 0.01 / 50 lots |
| Minimum price fluctuation | USD 0.01 |
| Stops level | 0 points |
| Profit / margin currency | USD / USD |
| Leverage | 1:1000 |
| Hedged margin discount | 100% |
| Spread marketing floor | USD 0.20 |
| Quote window | 01:00–23:59 server time |
| Trade window | 01:02–23:58 server time |

The broker server timezone and volume step were not supplied. The service keeps
them unknown until MT5 provides them. The advertised USD 0.20 spread is metadata,
not a maximum-spread promise; the live hard gate uses spread divided by M15 ATR.

## Implemented foundation

- `ReadOnlyMT5Client` fetches `D1`, `H4`, `H1`, `M15`, and `M5` closed bars from
  position 1 and has no execution API.
- Runtime symbol facts are compared with the configured `GOLD.i#` contract before
  the scanner is considered healthy.
- Data health fails closed for missing timeframes, stale prices, inactive broker
  sessions, unknown server time, invalid ATR, or inefficient spread.
- Setup IDs and the setup state machine are deterministic. Retest waiting expires
  on the tenth closed M15 candle.
- SQLite stores setup state, transition history, and an event-key-deduplicated
  notification outbox. This permits distinct management updates without resending
  the same update. Telegram delivery runs through a retryable worker outside market
  analysis.
- Position sizing is informational only and never rounds up to an unsafe broker
  minimum. The room-to-profit gate defaults to 3R.

## Still intentionally gated

An early-candidate event may be delivered as a watchlist notification when its
deterministic preliminary score is above 60. It must be labelled `WATCH_ONLY`,
must never call an execution API, and must later be updated as promoted or
cancelled using the same setup ID. A setup score is not treated as a probability.

Only the final `SNIPER_SIGNAL status=ENTRY_READY` event may be consumed by a
separate execution boundary. Early-candidate, promotion, and cancellation events
are informational and cannot authorize an order.

## Telegram subscriber approval

Run the notification worker with:

```powershell
$env:PYTHONPATH="$PWD\src"
python -m goldm_signal.notify.cli
```

The worker loads `.env`, stores subscriber state in
`runtime_data/goldm_signal.db`, and enforces this lifecycle:

1. A new private chat sends `/start` and becomes `PENDING`.
2. The requester receives no trading notifications while pending.
3. An administrator receives Approve and Reject buttons.
4. Only `APPROVED` chat IDs are selected by the broadcast sender.
5. `/stop` removes a non-admin chat from future broadcasts. A rejected chat can
   send `/start` to request access again.

`TELEGRAM_ADMIN_CHAT_IDS` accepts comma-separated chat IDs and falls back to
`TELEGRAM_CHAT_ID` for a single administrator. Admin authorization is checked
server-side for both inline callbacks and `/approve CHAT_ID` or
`/reject CHAT_ID`; hiding a button is never treated as authorization.

The same worker now tails the newest live `MQL5/Logs/*.log` file for each MT5
terminal under `%APPDATA%\\MetaQuotes\\Terminal`. It parses the EA's
`SNIPER_EARLY_CANDIDATE`, `SNIPER_EARLY_PROMOTED`, `SNIPER_SIGNAL`, and
`SNIPER_EARLY_CANCELLED` records, persists a byte cursor, and enqueues each event
exactly once before Telegram delivery. Use `--mt5-log PATH` to override discovery.
For a harmless end-to-end check, run once with `--debug-notification --once`;
the resulting message explicitly states that it is not an entry and opens no
order.

## Signal-only parity research

`GoldMSniperParity.mq5` now provides a no-order Strategy Tester reference using
D1/H4/H1 context, M15 setup, M5 confirmation, and M1 entry/management refinement.
The initial v1.4 backtest is documented in
`docs/goldm-sniper-v14-backtest-2026-08-12.md`. Its expectancy is negative, so
Telegram A+ promotion remains disabled.
