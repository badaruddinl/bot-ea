# Failure and recovery

PASS evidence includes broker rejection, duplicate EA/instance lease, profile
ownership refusal, Algo Trading off, dependency failure, market closed,
open-position restart, one-profile restart isolation, dual-terminal restart,
and Windows reboot.

Evidence: `../evidence/G18-failure-restart-e2e/certification.json` and the
profile-specific files under `../evidence/G18-failure-restart-e2e/native/`.

All recovery paths preserve profile ownership and keep production REAL orders
**DISABLED**.
