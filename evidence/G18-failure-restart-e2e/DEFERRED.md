# G18 Deferred Final Evidence

G18 status: **IN_PROGRESS**

The only unfinished evidence is an actual Windows/VM boot cycle.

Required completion artifact:

- `native/windows-restart.json`
- `native/windows-restart.sha256`

The two-phase probe is already prepared:

- `scripts/g18-windows-restart-probe.ps1 -Mode Prepare` captured the current
  boot ID and the exact GOLDI/GOLDM profile heartbeats.
- After a permitted VM reboot and probe autostart,
  `scripts/g18-windows-restart-probe.ps1 -Mode Complete` must prove:
  - the Windows boot ID changed;
  - both heartbeats were written after the new boot;
  - profile fingerprints, account logins, and servers stayed unchanged;
  - both process/chart identities changed;
  - both profiles still report order authority `DISABLED`.

The probe intentionally rejects completion on the current unchanged boot.
No reboot command is embedded in the probe.

Until these two artifacts exist:

- G18 must not be marked PASS;
- G19-G21 must not be started;
- production REAL order authority remains **DISABLED**.
