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

REAL orders: **DISABLED**
