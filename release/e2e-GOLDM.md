# GOLDM E2E

- Broker-data probe: actual REAL account, read-only, `orders_sent=0`,
  `order_api_calls=0`.
- Execution lifecycle: isolated Strategy Tester only.
- Telegram routing: admin-only; approved-audience leak count `0`.
- Live REAL order authority: **DISABLED**.
- Evidence: `../evidence/G10-reference-live-validation/GOLDM-probe.json`,
  `../evidence/G15-full-parity/native/goldm-execution-lifecycle-tester.json`,
  and `../evidence/G17-happy-path-e2e/certification.json`.
