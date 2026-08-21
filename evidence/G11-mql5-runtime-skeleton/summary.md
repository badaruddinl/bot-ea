# G11 MQL5 Runtime Skeleton

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. REAL order authority remains
disabled.

## Implemented

- shared strict MQL5 types for Bar, Tick, ProfileConfig, StrategyState,
  StrategyDecision, SignalPlan, EngineEvent, and ManagedPosition;
- compile-time \`BUILD_PROFILE_GOLDI\` and \`BUILD_PROFILE_GOLDM\` contracts;
- embedded canonical profile ID, fingerprint, symbol, magic, trade mode, and
  disabled order authority;
- thin GOLD.i and GOLDm entrypoints;
- bounded D1/H1/M15/M5/M1 closed-bar scheduler;
- each forming-bar timestamp is accepted once;
- bounded warm-up using closed bars only, without dispatch or trade;
- fail-closed wrong symbol/account/server/mode and closed-bar gap handling;
- bounded active-setup tick hook;
- no CTrade, OrderSend, network, database, file, history scan, or bridge call.

## Compile

MetaEditor build 6090:

\`\`\`text
GOLDI Result: 0 errors, 0 warnings
binary_sha256=040fbdcda5c6c34961147255bd643bba0e33d17e04bf632cddf56c8c6f62a703

GOLDM Result: 0 errors, 0 warnings
binary_sha256=f78d03b6e5c18b6406639208a2528a0930d2a2b3792bfd13eb5373c0121e03b9
\`\`\`

The binaries are intentionally distinct. Raw compile logs and generated EX5
files remain local/ignored; \`compile-evidence.json\` records their hashes,
sizes, source hashes, build, and clean result.

\`include_bundle_sha256=7ae182c7e63338c38f3965dcbe37059d903c8be0e495da63ffae1d5ed7435efe\`

## Tests

\`\`\`text
9 passed
pytest_junit_sha256=7b2835cd21a6c4e250ffe0d3c1f85919681f08f499db5f96d8fbbdf10066d060
compile_evidence_sha256=1068d09f3de07b6466c23a979ff6a6318828e964ccced4cf9362fb5f0f33cb0e
\`\`\`

Strategy semantics and executable order authority are not part of G11. They
remain for G12--G14. Strategy Tester parity and lifecycle evidence remain
required before release.

REAL orders: **DISABLED**
