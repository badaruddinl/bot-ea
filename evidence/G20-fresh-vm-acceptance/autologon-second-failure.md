# G20 second autologon cold-boot failure

Status: **FAIL retained as diagnostic evidence**

The second automatic-sign-in cold boot used hidden startup tasks and cleanly
closed preboot terminal processes. Windows automatically signed in, the lock
task returned the workstation to the lock screen, and the VM remained locked
for more than two minutes before operator authentication.

The strict verifier proved:

- boot identity advanced;
- startup mode was `AUTOLOGON_LOCKED_INTERACTIVE`;
- the supervisor task was running in interactive session 1;
- both exact terminal paths had one process in session 1;
- the bridge recovered with no pending or failed delivery;
- GOLDM emitted `ENGINE_STARTED`, `PROFILE_VALIDATED`, and
  `ENGINE_HEARTBEAT` with REAL order authority disabled;
- legacy Python strategy/orchestrator tasks remained disabled.

The verifier still returned FAIL because GOLDI emitted none of its three
required postboot events.

## Root cause

The GOLDI terminal journal recorded:

```text
Startup successfully initialized from start config "C:\bot-ea-g20\GOLDI.ini"
Charts open document chart 'GOLD.i#' from
'...\MQL5\Profiles\Charts\Default\chart01.chr' failed
Charts open chart 'GOLD.i#' failed for bot-ea\GoldEngine-GOLDi
```

The GOLDI MQL5 log and spool retained their preboot write time, proving that
the process existed but the profile-locked EA was never attached. This is why
process-only health was insufficient and why the event verifier correctly
kept the gate closed.

## Recoverable repair

With the supervisor stopped and no `terminal64.exe` process running, only the
failing `chart01.chr` was moved to a timestamped same-directory backup. No file
was deleted. After the supervisor restarted:

- the GOLDI chart visibly identified `GoldEngine-GOLDi`;
- the GOLDI spool grew from 1,571 to 3,584 bytes;
- the spool modification time advanced to 21 Aug 2026 23:51 local time.

Commit `820f977` adds `scripts/repair-g20-startup-chart.ps1`, which requires an
explicit acknowledgement, refuses repair while the exact terminal is running,
hash-verifies the backup, writes a JSON receipt, and has no deletion path.
Focused tests: 29 PASS. Fast regression: 826 tests and 77 subtests PASS.

Raw failed-run evidence remains on the VM:

- `C:\bot-ea-g20\preboot-auto-clean.json`
- `C:\bot-ea-g20\postboot-auto-clean.json`
- `C:\bot-ea-g20\verification-auto-clean.json`

Production REAL order authority remained **DISABLED** throughout.
