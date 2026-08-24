# Cross-profile isolation

- Symbols: GOLDI `GOLD.i#`; GOLDM `GOLDm#`.
- Magics: GOLDI `26081911`; GOLDM `26081912`.
- Terminals, accounts, state, audit, spools, and audiences are distinct.
- Actual VM terminal-path hashes are distinct.
- Cross-profile event count and privacy/state bleed count: `0`.
- Simultaneous capture: `602.01304` seconds.
- Evidence: `../evidence/G10-reference-live-validation/concurrency.json`,
  `../evidence/G17-happy-path-e2e/native/bridge-live-demo.json`, and
  `../evidence/G18-failure-restart-e2e/native/dual-terminal-restart.json`.
- Production REAL orders: **DISABLED**.
