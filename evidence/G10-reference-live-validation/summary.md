# G10 Reference Market-Data and Execution Validation

Status: **IN_PROGRESS — G11 UNBLOCKED, FINAL EXECUTION EVIDENCE DEFERRED**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. REAL order authority remains
disabled.

## Amended validation contract

- \`GOLDI_DEMO_VALIDATION\` remains the guarded live-DEMO validation profile.
- \`GOLDM_REAL_READ_ONLY\` derives from the current canonical GOLDM production
  fingerprint and permits only account/terminal/symbol metadata, tick, spread,
  and closed-bar reads.
- The GOLDm probe contains no order/check/send/position mutation API and records
  \`order_api_calls=0\`, \`orders_sent=0\`, and
  \`production_real_orders=DISABLED\`.
- GOLDm execution evidence is isolated Strategy Tester evidence after the
  profile-locked MQL5 binary exists; it is never reported as live broker E2E.
- GOLD.i and GOLDm retain distinct state, audit, audience, profile, symbol, and
  terminal-path requirements.

## Actual local evidence

The sanitized preflight was executed on 2026-08-21 and returned \`ready=false\`
only because both profiles currently resolve to the same terminal path:

\`prerequisites_sha256=90adb9f56ad946e0d36fa20fa2fdcab919b4b4d730f174f10fe2ac36eb3ace7a\`

Both account bindings are otherwise valid and the isolated validation
interpreter contains \`MetaTrader5==5.0.6090\`.

The GOLDm REAL read-only probe succeeded against terminal build 6090:

\`\`\`text
profile=GOLDM
validation=GOLDM_REAL_READ_ONLY
symbol=GOLDm#
account_trade_mode=real
access_mode=read_only
orders_sent=0
order_api_calls=0
latency_ms=6.736
\`\`\`

The probe contains only a hash of the login and terminal path. Its artifact
checksum is stored beside \`GOLDM-probe.json\`.

## Verification

\`\`\`text
focused_g10a_tests=21 passed
qt_environment_regression=1 passed
full_regression=829 passed, 1 skipped, 2 warnings, 141 subtests passed
full_junit_sha256=2b7fa162f37756d88b803662f8e18dc2624d65a1005fcbdca90bc38094df9592
acceptance_verifier_sha256=86a68537b7ce6c04527969d5aeec0df8b3617c1a46ac936b1d6e36bea1d6d0a9
production_real_orders=DISABLED
\`\`\`

The verifier correctly remains \`accepted=false\`; missing actual artifacts
cannot be replaced by prepared or synthetic evidence.

## Remaining G10 conditions

- a second isolated terminal/data path for GOLD.i DEMO;
- actual GOLD.i read-only probe and guarded DEMO lifecycle;
- simultaneous GOLD.i DEMO and GOLDm read-only capture with no state/privacy
  bleed;
- GOLDm batched Strategy Tester evidence after G15, including regression and
  historical holdout/walk-forward classification, 100% event/state parity,
  price error no greater than one tick, restart recovery, and zero duplicate;
- final verifier \`accepted=true\`.

The fail-closed G10A contract and tooling allow G11--G15 to proceed. G10B and
G10C remain required before release acceptance.
