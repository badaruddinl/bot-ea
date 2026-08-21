# G20 Fresh VM Acceptance

Status: **IN_PROGRESS**

Production REAL order authority remains **DISABLED**.

Locked unattended-start contract:

- the VM power-on event is sufficient; no interactive Windows login is needed;
- tasks trigger `At startup` and run under the Windows account that owns both
  MT5 profiles with `Run whether user is logged on or not`;
- the operator enters the Windows password once into Task Scheduler's protected
  credential store; the password is never written to Git, bot configuration,
  Telegram, logs, command lines, or evidence;
- `SYSTEM`, S4U, auto-logon, and the temporary G18 `ONLOGON` probes are rejected;
- the native profile-locked EAs remain the only strategy/order authorities;
  the optional bridge may fail without stopping trading continuity;
- a scheduled cold power-off/on acceptance must recover both terminals, exact
  profile/account/server ownership, open-position ownership, bounded spools,
  and bridge delivery before this gate can PASS.

Next evidence batch:

1. package the two exact G19-certified binaries and profile launch settings;
2. install password-backed startup tasks without exposing the credential;
3. remove/disable all temporary `ONLOGON` tasks and Python strategy workers;
4. cold power-cycle the VM without logging in;
5. inspect process, EA heartbeat, spool, bridge, and ownership evidence remotely;
6. log in only after evidence capture for operator-side visual confirmation.

Implemented pre-deployment batch:

- a native-only supervisor validates certified EA hashes, exact distinct terminal
  paths, profile/account/server/symbol/trade-mode contracts, and restarts only
  the two MT5 terminals plus the optional event-delivery bridge;
- the password-backed installer creates one delayed `AtStartup` task, verifies
  `LogonType=Password` and the boot trigger, and never serializes the credential;
- health/audit files are atomic and contain exact-path PIDs, restart counts,
  profile hashes/contracts, bridge state, Windows identity, and proof that REAL
  authority remains disabled;
- the EA emits a first internal health receipt after 60 seconds of quote flow and
  then at most once per hour. Its payload includes account login/server,
  trade mode, and order-authority state; the bridge suppresses the heartbeat from
  Telegram recipients;
- preboot/postboot capture records boot identity, task principal/trigger,
  supervisor health, exact terminal processes, legacy task state, Python process
  roles, spool offsets, and only the newly appended engine events;
- strict verifier requires a changed boot identity, supervisor start before
  interactive login, exactly one terminal per profile, exact fingerprint/account/
  server/symbol/mode, startup/profile/heartbeat events, recovered bridge, no
  legacy Python strategy worker, and disabled REAL authority;
- focused tests: 37 PASS; strict verifier mutation tests cover missing heartbeat,
  enabled authority, late startup, forbidden Python strategy, and legacy task;
- both profile EAs compile with MetaEditor build 6090 at 0 errors/0 warnings;
  quality coverage remains core 90.12% and strategy rules 82.66%.

G20 remains IN_PROGRESS until the password is entered directly on the VM and a
real cold boot is captured without interactive login.

REAL orders: **DISABLED**
