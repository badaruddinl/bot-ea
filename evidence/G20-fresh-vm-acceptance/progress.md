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
  server/symbol/mode/authority, startup/profile/heartbeat events, recovered
  bridge, no legacy Python strategy worker, and disabled GOLDm REAL authority;
- deterministic MT5 startup configs use the official `[StartUp]` mechanism and
  `MQL5\\Presets`: GOLDI DEMO order authority is enabled for actual E2E, while
  GOLDM REAL order authority and terminal live-trading permission stay disabled;
- focused tests: 37 PASS; strict verifier mutation tests cover missing heartbeat,
  enabled authority, late startup, forbidden Python strategy, and legacy task;
- both profile EAs compile with MetaEditor build 6090 at 0 errors/0 warnings;
  quality coverage remains core 90.12% and strategy rules 82.66%.

G20 remains IN_PROGRESS until the password is entered directly on the VM and a
real cold boot is captured without interactive login.

Actual VM deployment batch:

- exact VM worktree `c870b50` compiled both EAs with MetaEditor build 6090 at
  0 errors/0 warnings and installed SHA-256
  `7c9b68a41f16a4f6e930134badc61b60b90eb314bcd9d44c582f12ca2ff92ae6`
  (GOLDI) and
  `fe718009e75fda9dd3f15c04f07bc89b6b4ff48eb503c27cfd2d7f5df12a1579`
  (GOLDM);
- temporary G18 logon tasks and legacy Python orchestrator tasks are disabled;
  the old saved charts were removed after the final EA correctly rejected the
  first attempt as `DUPLICATE_EA_INSTANCE`;
- clean config-driven restart produced exact `ENGINE_STARTED`,
  `PROFILE_VALIDATED`, and internal `ENGINE_HEARTBEAT` events for both profiles:
  GOLDI account `108098316`, server `XMGlobal-MT5 5`, DEMO mode, authority
  enabled; GOLDM account `391425346`, server `XMGlobal-MT5 14`, REAL mode,
  authority disabled;
- password-backed task installation reported `LogonType=Password` and one
  `AtStartup` trigger; no password was read or persisted by repository code;
- Telegram dev token is stored with CurrentUser DPAPI and restrictive ACL. The
  bridge routes to dev admin chat `-5481117256`, with no subscriber audience;
- preboot bridge health: six events, four `DELIVERED`, two internal heartbeats
  `SUPPRESSED`, zero pending, zero failed, REAL disabled;
- preboot snapshot recorded the prior boot identity, task principal/trigger,
  and exact three-line offsets/hashes for each profile spool;
- the VM was cold-restarted and deliberately left at the Windows lock screen
  from 09:00 through 09:02 local time. No Ctrl+Alt+Del or interactive login was
  sent during the unattended startup window;
- final regression after the G20 changes: 809 fast tests plus 77 subtests PASS;
  154 slow tests plus 64 subtests PASS.

Postboot capture disproved the Session 0 design. The task started before login,
but MT5 did not execute either EA or append any postboot event. Details and the
strict FAIL result are retained in `session0-failure.md`. The experiment task is
disabled and all experiment processes are stopped.

The operator explicitly approved automatic console sign-in plus immediate
workstation lock after reviewing the Session 0 failure and Microsoft LSA-secret
warning. Interactive-token task tooling, Microsoft signature verification,
plaintext-password rejection, prompt lock marker, and verifier mutation cases
are implemented.

The first automatic-sign-in cold boot proved that sign-in and immediate lock
worked, but its strict verifier result was FAIL. A visible supervisor
PowerShell window was accidentally closed during evidence collection, so the
task was no longer running; Windows also restored previously open MT5 windows
before the supervisor could launch the profile configs. GOLDI therefore had no
new postboot startup/profile/heartbeat evidence. GOLDM correctly emitted
`MANUAL_INTERVENTION_DETECTED` because the REAL account had a live position
while its order authority remained disabled. The raw VM files are retained as
`C:\bot-ea-g20\preboot-auto.json`, `postboot-auto.json`, and
`verification-auto.json`; the diagnosis is recorded in
`autologon-first-failure.md`.

Corrections are now installed:

- scheduled supervisor and immediate-lock PowerShell hosts use hidden windows;
- Task Scheduler result evidence preserves the full unsigned 32-bit value;
- legacy configs default to no allowed ENGINE_ERROR exceptions;
- only GOLDM REAL with order authority disabled may explicitly allow
  `MANUAL_INTERVENTION_DETECTED`; every other ENGINE_ERROR still fails;
- both MT5 terminals were closed normally before the second cold boot so
  Windows could not restore them outside the supervisor path.

Post-correction regression: 823 fast tests plus 77 subtests PASS; 154 slow
tests plus 64 subtests PASS. The incremental quality gate PASSes with core
coverage 90.12% and strategy-rule coverage 82.66%.

The second cold boot reached the workstation lock automatically and remained
locked for more than two minutes while engines warmed up. G20 remains
IN_PROGRESS pending authenticated postboot capture and strict verifier PASS.

REAL orders: **DISABLED**
