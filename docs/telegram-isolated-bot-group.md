# Dedicated Telegram bot and group

Production notifications must use a dedicated bot identity and must not fall
back silently to the previous bot.

## Required private configuration

- `GOLD_NOTIFY_BOT_TOKEN`: token for the new bot; store with DPAPI on the VM,
  never in Git or process arguments.
- `GOLD_NOTIFY_EXPECTED_BOT_USERNAME`: exact username without `@`; startup
  fails if Telegram `getMe` returns another bot.
- `GOLD_NOTIFY_ADMIN_CHAT_IDS`: positive private chat IDs allowed to approve
  subscriptions and control workers.
- `GOLD_NOTIFY_ADMIN_CHAT_ID`: optional single-admin fallback.

The G20 bridge config must also contain `expected_bot_username`, the DPAPI
secret path, administrator IDs, and the orchestrator `subscriber_state_path`.

## Approval flow

1. Add the new bot to the intended GOLD.i group or open a private chat.
2. Send `/start` in that chat. The chat becomes `PENDING`; it never receives a
   signal merely because the bot was added.
3. An administrator approves the request using the inline approval card.
4. Only `APPROVED` chat IDs receive GOLD.i `POSITION_OPENED`, partial-close,
   and final-close notifications.
5. `/stop` or admin removal revokes delivery.

Group IDs are negative Telegram chat IDs and are valid subscription targets.
Administrator authority remains bound to positive private user chat IDs, so a
group member cannot gain worker controls.

GOLDm events are always routed only to administrator chat IDs. GOLDm never
uses the GOLD.i subscriber/group list.

## Message language and trade context

All active Telegram bridge and approval-orchestrator messages are English-only.
Trade lifecycle messages expose `Strategy`, `Strategy mode`, and `Trade reason`
as separate fields. The strategy mode identifies the decision path, such as
`MOMENTUM`, `RANGE`, `SCALPER_MOMENTUM`, or `H1_M5_M1_RETEST`; the trade reason
records the causal entry decision, such as `MOMENTUM_ENTRY` or
`STRONG_FIRST_CONFIRMATION`. This context is persisted with an EA-owned
position and is repeated on partial close, final close, and restart recovery.
