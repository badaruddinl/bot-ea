# Known limitations

- GOLDM production REAL order authority is disabled and was never exercised by
  engineering E2E; GOLDM execution evidence is Strategy Tester only.
- Enabling any REAL authority remains a separate, explicit human operation and
  is not part of this release.
- Python is retained as the certified reference; removing it requires a later
  explicit decision.
- The G20 unattended design uses Windows automatic sign-in followed by an
  immediate lock because MT5 cannot execute EAs in Session 0.
- Internet Telegram latency is not certified; only internal enqueue-to-sender
  latency is measured.
- Broker symbol sessions, spread, and margin constraints remain external
  dependencies and always fail closed when uncertain.
- Strategy semantics are the frozen baseline; this release is a migration and
  parity release, not a strategy-tuning release.
