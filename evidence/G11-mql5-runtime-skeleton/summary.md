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
binary_sha256=6142b2b840e400d11fb5c6c1a3bb8eb553d15c56f4c5119642f6697724713fb2

GOLDM Result: 0 errors, 0 warnings
binary_sha256=86acaf6bf47d80532575c32255089efa9dbf44eb8973c48582a4a2c03aa95f56
\`\`\`

The binaries are intentionally distinct. Raw compile logs and generated EX5
files remain local/ignored; \`compile-evidence.json\` records their hashes,
sizes, source hashes, build, and clean result.

## Tests

\`\`\`text
9 passed
pytest_junit_sha256=7b2835cd21a6c4e250ffe0d3c1f85919681f08f499db5f96d8fbbdf10066d060
compile_evidence_sha256=470e90b78d1e289af4822986cf9689279ee7159c11d086a3402605c03aa64d16
\`\`\`

Strategy semantics and executable order authority are not part of G11. They
remain for G12--G14. Strategy Tester parity and lifecycle evidence remain
required before release.

REAL orders: **DISABLED**
