# G20 Session 0 Failure Evidence

Status: **FAIL — retained as causal evidence**

Production REAL order authority remained **DISABLED**.

## Experiment

- Windows task: password-backed `AtStartup`, `Run whether user is logged on or
  not`, exact owner account, delayed 30 seconds.
- VM was rebooted and deliberately left at the lock screen for more than four
  minutes before interactive login.
- The supervisor started at `2026-08-21T14:01:44+00:00`; the first interactive
  Explorer session was not observed until `2026-08-21T14:06:51+00:00`.
- Windows boot identity advanced from `2026-08-21T09:37:23.5000000Z` to
  `2026-08-21T14:00:18.5000000Z`.

## Contradicting evidence

- Both background `terminal64.exe` instances ran in Windows `Services` session
  0, not Console session 1.
- Neither profile appended `ENGINE_STARTED`, `PROFILE_VALIDATED`, or
  `ENGINE_HEARTBEAT`; both spools remained at their exact preboot three-line
  offsets and hashes.
- Neither MQL5 journal contained an `OnInit()`/`GOLD_ENGINE_READY` record after
  the reboot. The last valid native-engine records remained from the interactive
  preboot run.
- GOLDM restarted repeatedly in session 0. After interactive login, Windows
  restored an additional GOLDI process in Console session 1, producing a strict
  duplicate-process failure.
- The strict verifier returned FAIL for missing postboot events, exact-process/
  supervisor PID mismatches, and duplicate/missing terminal ownership.

## Safety response

- `BOT-EA G20 Native Supervisor` was stopped and disabled.
- All experiment terminal and bridge processes were stopped.
- Temporary G18 tasks and legacy Python strategy tasks remain disabled.
- This experiment is not used as evidence that G20 passed.

## Platform constraint

Microsoft documents that services/session-0 processes use a noninteractive
window station and cannot directly interact with the user desktop on supported
Windows versions. A GUI process must instead be created in an interactive user
session. Microsoft also documents automatic sign-in followed by immediate lock
as the mechanism used by Automatic Restart Sign-On.

- https://learn.microsoft.com/en-us/windows/win32/services/interactive-services
- https://learn.microsoft.com/en-us/windows-server/security/windows-authentication/winlogon-automatic-restart-sign-on-arso
- https://learn.microsoft.com/en-us/sysinternals/downloads/autologon

## Required decision

The remaining viable design is **automatic console sign-in plus immediate
workstation lock**, followed by interactive-token startup of MT5. This removes
manual login but stores the Windows credential as an LSA secret. Microsoft warns
that a local administrator can retrieve and decrypt that secret. Enabling this
mechanism therefore requires explicit operator authorization and a revised G20
acceptance contract; it is not inferred from the failed Session 0 experiment.
