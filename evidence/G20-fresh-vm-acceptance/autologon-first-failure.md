# G20 first autologon cold-boot failure

Status: **FAIL retained as diagnostic evidence**

The first `AUTOLOGON_LOCKED_INTERACTIVE` cold boot established that Windows
automatically signed in to the configured console account and that the
independent lock task returned the workstation to the lock screen promptly.
It did not satisfy the complete G20 acceptance contract.

The strict verifier reported:

1. `startup task is not running`;
2. `GOLDI is missing postboot events: ENGINE_HEARTBEAT, ENGINE_STARTED,
   PROFILE_VALIDATED`;
3. `GOLDM emitted ENGINE_ERROR after boot`.

Diagnosis:

- the supervisor PowerShell host was visible and was mistakenly closed while
  opening a shell for evidence capture; Task Scheduler retained result
  `3221225786` (`0xC000013A`), and the health record became stale;
- Windows restored MT5 windows that had been open before reboot, so the
  supervisor adopted already-running processes instead of launching the
  deterministic profile configs;
- GOLDM had a live REAL position not owned by the disabled-authority engine.
  `MANUAL_INTERVENTION_DETECTED` was therefore the expected fail-closed safety
  response, not an EA-created REAL order;
- the original evidence collector attempted to coerce Task Scheduler's
  high-bit result to signed `Int32`; this overflow was corrected before the
  retained snapshot and verifier were generated.

Corrections are bound to commits `4ff978c`, `fe11a10`, `81af500`, and
`587872d`. The failure is not promoted to PASS and is not substituted for the
required second cold-boot evidence.

Raw evidence retained on the G20 VM:

- `C:\bot-ea-g20\preboot-auto.json`
- `C:\bot-ea-g20\postboot-auto.json`
- `C:\bot-ea-g20\verification-auto.json`

Production REAL order authority remained **DISABLED** throughout.
