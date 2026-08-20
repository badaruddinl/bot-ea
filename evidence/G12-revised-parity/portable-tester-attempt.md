# Portable Strategy Tester Attempt

Status: **DEFERRED — ACCOUNT BINDING REQUIRED**

An isolated portable MT5 build 6090 clone was created without copying the
operator data-path \`Config\` directory or account credentials. Installation
binaries and non-secret \`Bases\` history/symbol cache were used.

The parity harness compiled inside the clone with:

\`\`\`text
Result: 0 errors, 0 warnings
\`\`\`

The terminal loaded the fail-closed tester configuration but refused to start:

\`\`\`text
tester not started because the account is not specified
\`\`\`

The active GOLDm REAL terminal was not stopped, restarted, or modified. A locked
2026 GOLDm history file was not forced or copied. No credential file was copied.
No order API exists in the harness.

Native Strategy Tester execution remains required before G12 PASS and will run
after an isolated terminal receives an explicit account login.

REAL orders: **DISABLED**
