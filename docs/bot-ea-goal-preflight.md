# Bot EA Goal Preflight — Definition of Ready

## Purpose

This document lists what must be available before activating
`BOT-EA-CODEX-GOAL.md`. It prepares reproducible engineering work; it does not
start the goal, change the trading engine, or authorize REAL orders.

## Current pre-goal snapshot

Observed target:

```text
repository: badaruddinl/bot-ea
target branch: feature/global-orchestrator
candidate remote tip: b042d51cfc3b2ea1f9aa048054af03d79d79726e
parent: 02cf5dd342c85e70fe81524dfc678c873366e869
tree: ff84bce1ae72cebe77b7bd10328e9343fb7e1df3
origin/main: 32927bd (older and not the goal target)
```

The candidate must be fetched and resolved again at goal activation. The goal
document is currently a local, untracked preparation artifact and therefore is
not yet part of the remote repository contract.

## 1. Human decisions required

- [ ] Explicit instruction that activates `BOT-EA-CODEX-GOAL.md`.
- [ ] Confirm the target integration branch and who may merge to it.
- [ ] Confirm REAL remains disabled throughout engineering.
- [ ] Name the human authorized to activate the final GOLDm REAL profile.
- [ ] Name the human who accepts fresh-VM and final release evidence.
- [ ] Decide where immutable evidence and release binaries will be retained.

## 2. Git and source prerequisites

- [ ] Read access and push access to `badaruddinl/bot-ea`.
- [ ] Exact remote target tip fetched immediately before G00.
- [ ] Clean dedicated worktree from that exact SHA.
- [ ] No untracked research/runtime data inside the evidence checkout.
- [ ] Baseline commit, parent, tree, ref, and relevant blob hashes recorded.
- [ ] CI/check status for the baseline recorded rather than assumed.
- [ ] Existing Python test entrypoints and known failures recorded.
- [ ] Rollback reference for the current Python deployment recorded.
- [ ] Decision on committing the goal document as the first post-baseline
      governance commit.

Recommended layout outside the dirty working checkout:

```text
bot-ea-baseline-b042d51/      immutable inspection worktree
bot-ea-goal-integration/     active goal worktree after authorization
bot-ea-evidence/             immutable or append-only evidence storage
bot-ea-release-staging/      generated binaries, never mixed with source
```

## 3. Windows, MT5, and compiler prerequisites

Provide exact paths and versions without committing secrets:

- [ ] Windows version/build used for development and fresh-VM acceptance.
- [ ] MetaTrader 5 terminal build and executable path for GOLD.i.
- [ ] Separate MetaTrader 5 build/path for GOLDm.
- [ ] MetaEditor build and `metaeditor64.exe` path.
- [ ] A reproducible command-line MQL5 compile command.
- [ ] Strategy Tester availability for both symbol profiles.
- [ ] Terminal “Max bars in chart” and history settings recorded.
- [ ] Timezone, DST, locale, decimal format, and VM clock synchronization
      recorded.
- [ ] A disposable snapshot/rollback point before installing test binaries.

Do not assume two terminals with the same build share account state safely.

## 4. Broker and account prerequisites

### GOLD.i

- [ ] Dedicated DEMO account.
- [ ] Exact login/server supplied through secure environment configuration.
- [ ] `GOLD.i#` visible and trading enabled.
- [ ] Algo Trading and external Python API policy recorded during reference
      validation.

### GOLDm

- [ ] Production profile identity recorded but REAL activation disabled.
- [ ] Separate safe DEMO mirror for engineering E2E.
- [ ] The DEMO mirror cannot submit to the production account.
- [ ] Wrong account/mode/server tests are possible without touching REAL.

### Symbol contract per profile

Export and retain:

- [ ] exact symbol name;
- [ ] digits, point, tick size, tick value;
- [ ] contract size and profit/margin currency;
- [ ] minimum/maximum/step volume;
- [ ] stops and freeze levels;
- [ ] supported filling/order modes;
- [ ] leverage and margin behavior;
- [ ] quote/trade sessions and DST behavior;
- [ ] representative normal and extreme spreads.

## 5. Market-data prerequisites

- [ ] Causal closed-bar data for M1, M5, M15, H1, and D1.
- [ ] Tick data with bid, ask, millisecond timestamp, and spread where required.
- [ ] Exact broker-server timezone mapping, including DST transitions.
- [ ] Separate GOLD.i and GOLDm datasets or a documented normalization contract.
- [ ] Dataset hashes, source, export command, range, and completeness report.
- [ ] A deterministic same-bar ambiguity policy.
- [ ] Warm-up boundary and non-tradable warm-up rules.
- [ ] Current-behavior corpus covering Revised, Bear, execution, cancellation,
      expiry, and restart scenarios for each profile.

Public-web data may support research context but cannot substitute for broker
data in parity, execution, or acceptance evidence.

## 6. Telegram, database, and bridge prerequisites

- [ ] Dedicated test bot or a safely isolated test scope.
- [ ] Admin private chat IDs and a GOLD.i subscriber test chat/group.
- [ ] No production token in source, logs, screenshots, or evidence.
- [ ] Defined event/audience matrix for GOLD.i and GOLDm.
- [ ] Durable outbox/spool location with disk quota and rotation policy.
- [ ] Database location, schema migration policy, backup, and restore test.
- [ ] Failure injection method for bridge, DB, Telegram, and backlog recovery.
- [ ] At-least-once delivery and idempotent `event_id` acceptance criteria.

The bridge must be testable while stopped; EA decision, execution, and position
management must continue independently.

## 7. Quality-tooling prerequisites

- [ ] Supported Python version pinned for reference tooling.
- [ ] Reproducible dependency lock or frozen environment report.
- [ ] Formatter/linter selected and configured.
- [ ] Type checker selected and scoped.
- [ ] Unit, profile, cross-profile, causal, restart, and parity test commands.
- [ ] Coverage policy for safety-critical modules.
- [ ] MQL5 compile warnings treated as recorded gate evidence.
- [ ] Deterministic fixture and golden-event update policy.
- [ ] Mutation tests for swapped symbol/magic/audience/mode/config and removed
      execution guards.

Adding quality tooling must be its own preparation or goal batch. Do not mix
tool bootstrap with strategy changes.

## 8. Fresh-VM and release prerequisites

- [ ] Fresh Windows VM or clean snapshots for both profiles.
- [ ] Installation runbook that starts from only MT5 plus the relevant `.ex5`.
- [ ] Binary transfer mechanism and checksum verification.
- [ ] Separate GOLD.i and GOLDm profile manifests.
- [ ] Rollback binaries and rollback procedure.
- [ ] Artifact naming/version policy.
- [ ] SHA-256 generation and verification procedure.
- [ ] Resource/latency measurement tooling.
- [ ] Acceptance evidence capture that does not expose credentials.

## 9. Evidence workspace required at G00

Create only after explicit goal activation and baseline re-resolution:

```text
evidence/
  G00-baseline/
    baseline.json
    source-hashes.txt
    environment.md
    current-test-run.log
    ci-status.md
  ledger.md
```

Every later gate receives its own directory containing commands, raw outputs,
exit codes, summaries, and artifact hashes. Documentation claims without raw
evidence do not turn a gate PASS.

## 10. Definition of Ready

The goal is ready to start only when all items below are true:

- [ ] Explicit human activation received.
- [ ] Exact target tip resolved again.
- [ ] Clean baseline and integration worktrees exist.
- [ ] Goal document is reviewed and its repository status is decided.
- [ ] GOLD.i DEMO and GOLDm safe DEMO mirror are available.
- [ ] GOLDm REAL remains disabled.
- [ ] MT5 and MetaEditor versions/paths are known.
- [ ] Broker symbol contracts are exported.
- [ ] Required broker data and hashes are available.
- [ ] Test Telegram/DB/bridge environment is isolated.
- [ ] Fresh-VM/snapshot capacity exists.
- [ ] Evidence and release storage locations exist.
- [ ] Human acceptance and REAL-activation owners are named.

If any item is missing, preparation may continue, but the associated goal gate
must not be claimed PASS.

## 11. First authorized sequence after readiness

1. Re-fetch `origin/feature/global-orchestrator`.
2. Record exact SHA/parent/tree/ref and clean status.
3. Run the untouched baseline tests and record all failures.
4. Record Python, Windows, MT5, MetaEditor, broker, and symbol metadata.
5. Hash the relevant source/config files.
6. Create G00 evidence and update only the G00 ledger cells supported by facts.
7. Review G00 before beginning G01.

No MQL5 engine implementation, strategy refactor, or runtime migration should
begin before that sequence is authorized and G00 evidence is reviewable.
