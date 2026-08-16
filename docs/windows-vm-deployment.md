# GOLDM demo-only Windows VM release runbook

This runbook applies to the frozen GOLDM strategy 1.72 release line. The
production engine is the exact `ALL` baseline descended from commit
`6a4150322433640d555506a3ce9bb6f3065d2d32`. `EntrySidePolicy` and
`NotificationSideFilter` are runtime controls; neither selects or modifies the
strategy engine.

The release is DEMO/shadow only. The validator requires
`GOLDM_ALLOW_LIVE_ACTIVATION=false`, requires `GOLDM_EXECUTION_MODE=off` at
cutover, and refuses REAL, CONTEST, or unclassified MT5 accounts. Do not weaken
those gates to make deployment pass.

## Required external inputs

Prepare these outside Git and record their independently verified SHA-256
digests:

1. A dedicated Windows x64 VM and operator account. Do not reuse an interactive
   workstation whose MT5 terminal may reconnect to an unknown last account.
2. CPython 3.14 x64, with the exact `python.exe` path and SHA-256.
3. One standard (non-portable) MetaTrader 5 installation, its exact
   `terminal64.exe`, `MetaEditor64.exe`, and terminal data directory.
4. A manually authenticated MT5 DEMO hedging account. Never place its password
   in Git, Telegram, an environment file, command arguments, or logs.
5. A sealed offline wheelhouse containing only the CPython 3.14 win_amd64
   `MetaTrader5==5.0.5735` and `numpy==2.4.2` wheels, the hashed
   `requirements-goldm-live.lock`, and `goldm-wheelhouse-manifest.json`. The
   operator-approved manifest SHA-256 is the root of trust.
6. A private Telegram bot token and positive private-user admin chat IDs.

## Required GitHub runner gate

Register the VM as a repository self-hosted runner using GitHub's ephemeral
registration token and these labels:

```text
self-hosted, Windows, X64, goldm-mt5
```

Run it as a service under the dedicated operator account. The required
`mt5-release-windows` check only performs the full release verification and
clean MQL compilation; it does not deploy, start MT5, or submit an order. Do
not merge the release PR until both `full-python-windows` and
`mt5-release-windows` pass and the independent review requirement is met.

## Prepare the private runtime environment

Run PowerShell as Administrator from an exact checkout of the approved release
commit. On the first bootstrap attempt, the script creates `.env` from
`.env.example` and deliberately stops. Fill every `UNSET` value. In particular:

- `MT5_PATH` and `MT5_DATA_PATH` must be absolute and identify the exact
  standard terminal instance;
- `MT5_LOGIN`, `MT5_SERVER`, and both `GOLDM_EXPECTED_*` values must match;
- `GOLDM_EA_SESSION_ID` must be a unique 16-96 character safe token;
- `GOLDM_ALLOW_LIVE_ACTIVATION` must remain exactly `false`;
- `GOLDM_EXECUTION_MODE` must remain exactly `off`;
- entry and notification policies start at `ALL` independently.

The bootstrap seals this source file into
`runtime_data\config\runtime.env` with private ACLs. Scheduled Tasks use only
that private snapshot; the repository `.env` is not the runtime authority.

## First bootstrap

Resolve every value explicitly. Do not replace full commit IDs or SHA-256
digests with branch names, `HEAD`, globs, or short hashes in an approved run.

```powershell
$repo = 'C:\GoldM\bot-ea'
$python = 'C:\Program Files\Python314\python.exe'
$terminal = 'C:\Program Files\MetaTrader 5\terminal64.exe'
$terminalData = 'C:\Users\goldm-demo\AppData\Roaming\MetaQuotes\Terminal\INSTANCE_ID'
$editor = 'C:\Program Files\MetaTrader 5\MetaEditor64.exe'
$wheelhouse = 'D:\sealed-inputs\goldm-wheelhouse-cp314-win-amd64'
$releaseCommit = 'REPLACE_WITH_APPROVED_40_HEX_COMMIT'
$pythonSha256 = 'REPLACE_WITH_64_HEX_SHA256'
$wheelhouseManifestSha256 = 'REPLACE_WITH_64_HEX_SHA256'

powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File "$repo\scripts\bootstrap-goldm-windows-vm.ps1" `
  -RepoRoot $repo `
  -PythonExecutable $python `
  -PythonSha256 $pythonSha256 `
  -TerminalExecutable $terminal `
  -TerminalDataPath $terminalData `
  -MetaEditorPath $editor `
  -WheelhousePath $wheelhouse `
  -WheelhouseManifestSha256 $wheelhouseManifestSha256 `
  -ReleaseCommit $releaseCommit
```

Bootstrap validates the demo-only runtime contract, builds an offline sealed
release, runs full test discovery, compiles the EA and importer with zero
errors/warnings, creates the private database/config, and installs a disabled
Scheduled Task. It does not enable entry automatically.

## Stage-only cutover

Use `-StageOnly` for the first cutover. It deploys and verifies the release but
keeps the worker task disabled:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File "$repo\scripts\deploy-goldm-windows-vm.ps1" `
  -RepoRoot $repo `
  -PythonExecutable $python `
  -PythonSha256 $pythonSha256 `
  -TerminalExecutable $terminal `
  -TerminalDataPath $terminalData `
  -MetaEditorPath $editor `
  -WheelhousePath $wheelhouse `
  -WheelhouseManifestSha256 $wheelhouseManifestSha256 `
  -ReleaseCommit $releaseCommit `
  -StageOnly
```

Only after `STAGE_ONLY_OK`, attach `GoldMSniperParity` manually to `GOLD.i#`
M15 in the exact DEMO terminal profile, keep entry OFF, and save the profile.
The manual chart step is required because MT5 exposes no safe supported API for
attaching an EA to a chart.

## Demo cutover and proof

Rerun the same deploy command without `-StageOnly`. Success requires all of the
following evidence before `DEPLOY_OK` is emitted:

- immutable source, production-input, interpreter, wheelhouse, and runtime
  configuration hashes;
- exact connected DEMO login/server/trade-mode and hedging account proof;
- strategy 1.72 `ALL` session evidence from a fresh EA configuration log;
- database integrity and a flat broker book at cutover;
- exact Scheduled Task action/process identity;
- fresh Telegram `getUpdates` readiness with no competing poller.

The deployment starts in execution mode OFF. Enabling DEMO entry is a separate
admin action after reviewing `/status` and `/account`; REAL activation remains
impossible while the deployment kill switch is false.

## Exact normal update

The updater defaults to `release/goldm-core-v2`, fetches one named remote ref,
and requires the expected full commit. Always pass the approved commit
explicitly:

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass `
  -File "$repo\scripts\update-goldm-windows-vm.ps1" `
  -RepoRoot $repo `
  -PythonExecutable $python `
  -PythonSha256 $pythonSha256 `
  -TerminalExecutable $terminal `
  -TerminalDataPath $terminalData `
  -MetaEditorPath $editor `
  -WheelhousePath $wheelhouse `
  -WheelhouseManifestSha256 $wheelhouseManifestSha256 `
  -Remote origin `
  -RemoteBranch 'release/goldm-core-v2' `
  -ExpectedCommit $releaseCommit
```

## Monitoring checklist

Monitoring is read-only until all checks are healthy:

1. GitHub required checks remain green for the deployed commit.
2. The Scheduled Task is running under the dedicated operator and its action is
   bound to the sealed release manifest and private runtime config hashes.
3. `/status` reports execution OFF or DEMO, never LIVE; `/account` reports the
   expected DEMO login/server and hedging scope.
4. Telegram polling readiness remains fresh and no `409 Conflict`/competing
   poller is recorded.
5. MT5 logs continue to emit the expected run/session, account binding, and
   production contract without `runtime_safe_halt`, account drift, or
   unreconciled broker actions.
6. R1/R2/R3 mutations reconcile to durable confirmed/failed state; UNKNOWN is
   investigated and is never blindly retried.

If account identity changes, Telegram readiness degrades, an unexpected process
appears, or any source/config hash drifts, disable the Scheduled Task and leave
entry OFF. Do not improvise a REAL fallback.

## Backup and recovery

Use `backup-goldm-windows-vm.ps1` to create a sealed backup manifest. Recovery
must use `restore-goldm-windows-vm.ps1`, the exact manifest and sidecar digest,
explicit restore switches, and the acknowledgement required by the script.
Deployment rollback re-proves the terminal session and Telegram readiness
before restarting the previous worker. Never manually copy a database or
runtime environment over a running worker.
