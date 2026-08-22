# Rollback

1. Keep production REAL order authority disabled.
2. Disable the exact `BOT-EA G20 Native Supervisor` task and stop only the two
   configured terminal executable paths.
3. Preserve current binaries, startup configs, state, spools, and hashes in a
   timestamped backup; never delete them.
4. Restore the previous certified profile-specific binaries and their exact
   config hashes. Do not cross-copy GOLDI/GOLDM artifacts.
5. Validate symbol, account, server, mode, magic, fingerprint, and binary hash
   before either terminal starts.
6. Start the supervisor and require new `ENGINE_STARTED`, `PROFILE_VALIDATED`,
   and `ENGINE_HEARTBEAT` receipts for both profiles.
7. Confirm bridge recovery and zero duplicate/foreign ownership events.
8. If any check fails, leave both authorities disabled and keep the task
   stopped for operator review.

Packaged pre-G20 rollback binaries:

- `rollback/GoldEngine-GOLDi-pre-G20.ex5` —
  `a98663d1cffe64798c9c282d00334390e4655bb6192cb3b930d68bdcc23070f6`;
- `rollback/GoldEngine-GOLDm-pre-G20.ex5` —
  `1b0f50b478d9473315f899aaf31c1f107c69430537a7edbbe561ac97973f9f07`.

Their lineage is `../evidence/G19-resource-storage-latency/certification.json`.

Rollback never grants REAL authority and never relies on Telegram/DB success to
permit an order.
