# G18 Deferred Final Evidence — Resolved

G18 status: **PASS**

The previously deferred Windows/VM boot cycle is complete.

Required completion artifact:

- `native/windows-restart.json`
- `native/windows-restart.sha256`

The completed two-phase probe recorded:

- `scripts/g18-windows-restart-probe.ps1 -Mode Prepare` captured the original
  boot ID and the exact GOLDI/GOLDM profile heartbeats.
- After the permitted VM reboot and probe autostart,
  `scripts/g18-windows-restart-probe.ps1 -Mode Complete` proved:
  - the Windows boot ID changed;
  - both heartbeats were written after the new boot;
  - profile fingerprints, account logins, and servers stayed unchanged;
  - both runtime identities changed while diagnostic ChartIDs remained stable;
  - both profiles still report order authority `DISABLED`.

The probe intentionally rejected completion on the unchanged pre-reboot boot.
No reboot command is embedded in the probe.

Both artifacts now exist and strict certification passes. Production REAL order
authority remains **DISABLED**.
