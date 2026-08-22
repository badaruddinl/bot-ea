# G10D Remove Application Surfaces

Status: **PASS**

Scope: SHARED. REAL order authority remains disabled.

## Removed

- Qt and Tk GUI modules;
- desktop runtime coordinator;
- WebSocket service;
- desktop/WebSocket entrypoints;
- UI/WebSocket launcher scripts;
- UI, desktop runtime, WebSocket, and application packaging tests;
- obsolete application manuals, runbooks, handoff, and session documents;
- \`PySide6\` and \`websockets\` package declarations.

The engine, MT5 adapter, deterministic guards, Revised/Bear rules, portfolio
worker, orchestrator, Telegram bridge, audit, and validation tooling remain.

## Enforced invariant

\`tests/test_no_app_surfaces.py\` prevents the removed files, dependencies,
entrypoints, and public exports from returning.

A repository scan found no \`PySide6\`, WebSocket service, Qt/Tk app, desktop
runtime, or related entrypoint reference under \`src/\`, \`scripts/\`,
\`.github/\`, or \`pyproject.toml\`.

## Test schedule

Default \`pytest\` excludes historical research/deployment matrix tests:

\`\`\`text
612 passed
154 deselected
77 subtests passed
duration=86.64s
fast_junit_sha256=8f2f0bb2d09de2e4be28810215928e33131ef0ed9d08a62d3cd1151492fad52d
\`\`\`

The explicit release subset remains mandatory:

\`\`\`text
154 passed
612 deselected
64 subtests passed
duration=362.89s
slow_junit_sha256=e6aa3e60115ccc88f1655f9952aacc317abf1370547e243534accc5d776a0630
\`\`\`

Combined coverage is all 766 collected tests. CI explicitly runs
\`-m "slow or not slow"\`; no release assertion was removed.

REAL orders: **DISABLED**
