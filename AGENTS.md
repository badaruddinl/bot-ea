# Bot EA Repository Instructions

## Scope and authority

These instructions apply to the entire `bot-ea` repository.

The repository product is an MT5 trading engine/EA and its validation,
orchestration, audit, and Telegram bridge tooling. Do not add a desktop GUI,
Qt/Tk application, WebSocket service, or application packaging surface. The
MetaTrader terminal itself is an external broker terminal, not this product's
UI.

`BOT-EA-CODEX-GOAL.md` is the authoritative target contract only after the
user explicitly activates that goal. Until then, this repository is in
**PRE-GOAL PREPARATION**. Preparation may inventory, document, create clean
worktrees, record reproducible environment metadata, and scaffold evidence or
validation tooling. Preparation must not change strategy semantics, trading
runtime behavior, profile risk, deployment state, or broker execution.

Never infer goal activation from the presence of the goal document, a branch
name, an unfinished ledger, or a request to prepare prerequisites.

## Safety hierarchy

1. Human and platform safety instructions.
2. Explicit current user request.
3. Activated `BOT-EA-CODEX-GOAL.md` contract.
4. This `AGENTS.md`.
5. Existing repository documentation and conventions.

If instructions conflict, stop the affected batch, record the conflict, and
request a decision. Do not silently choose the less safe interpretation.

## Non-negotiable trading safety

- REAL order activation is human-only and must never be inferred.
- Keep GOLDm production REAL orders disabled during preparation, engineering,
  tests, migration, parity work, and DEMO validation.
- Do not use a production account for engineering order E2E. Prefer an
  explicitly isolated GOLDm DEMO mirror. If the broker does not offer a
  semantically equivalent GOLDm DEMO contract and the user explicitly accepts
  the alternate path, the production account may be used only for read-only
  broker metadata, tick, spread, and closed-bar capture. That exception must
  expose no order API, must record `orders_sent=0`, and must pair with isolated
  Strategy Tester execution evidence. It never grants REAL order authority.
- Never log, print, commit, screenshot, or paste passwords, bot tokens, account
  secrets, OTPs, or full private environment files.
- Fail closed on symbol, account, server, trade mode, profile, magic, sizing,
  data freshness, spread, drift, invalidation, margin, or broker uncertainty.
- A bridge, Telegram, database, UI, or telemetry failure must never create an
  order or broaden trading authority.
- Never run two order authorities for the same profile, account, symbol, and
  magic. In particular, do not run a Python executor and an order-sending EA in
  parallel during migration.

## Required profile isolation

GOLD.i and GOLDm share strategy primitives only. They never share identity or
authority.

| Contract | GOLD.i | GOLDm |
|---|---|---|
| Profile | `GOLDI` | `GOLDM` |
| Symbol | `GOLD.i#` | `GOLDm#` |
| Intended mode | DEMO | REAL production / DEMO mirror for engineering |
| Magic | `26081911` | `26081912` |
| Audience | approved GOLD.i subscribers | admin-only |
| State/audit | dedicated namespace | dedicated namespace |
| Terminal | dedicated executable/path | dedicated executable/path |

No profile may fall back to the other profile's symbol, executable, login,
server, config, state, magic, risk, audience, or open positions.

## Baseline discipline

- `origin/main` is the only canonical source of truth for implementation,
  release, deployment, and future baselines.
- Fetch before every batch and create a clean branch from the exact current
  `origin/main` SHA. Never continue new work from an old feature branch.
- Use `feature/<concern>` for additions and `hotfix/<concern>` for corrections
  to behavior already present on main.
- Every feature/hotfix reaches main through a pull request. Do not push commits
  directly to main, rewrite main, or treat an unmerged branch as production
  truth.
- Merge only after required tests pass, use a merge commit, then delete the
  remote feature/hotfix branch. Tags and deployment candidates must resolve to
  main or an explicitly identified PR commit awaiting merge.
- Fetch before the first batch and resolve the exact remote tip to a full SHA.
- A branch name is not evidence. Record commit SHA, parent SHA, tree SHA,
  remote ref, relevant blob hashes, and environment metadata.
- Use a clean dedicated worktree. Untracked research data or a dirty checkout
  makes the exact-baseline gate fail.
- Do not amend, force-push, rebase, retag, or otherwise rewrite an audited
  baseline.
- Preserve the Python implementation as the reference until certified parity
  makes a replacement removable.

## Repository and tool workflow

- Prefer the latest Ubuntu WSL distro for repository work.
- Use the Windows `xuva` proxy for Git, search, reads, and test commands when
  practical: `xuva git`, `xuva rg`, `xuva read`, and `xuva python`.
- For Windows-drive checkouts, run Git with a safe-directory override when
  required and preserve the repository's CRLF behavior.
- Use PowerShell only for Windows-native operations such as MT5, MetaEditor,
  Scheduled Tasks, Windows process control, packaging, or screenshots.
- Use `rg`/`rg --files` before slower search tools.
- Use `apply_patch` for deliberate text edits. Do not overwrite whole files for
  a small change.
- Preserve unrelated user changes and untracked research artifacts.
- Never use destructive Git commands such as `reset --hard` or broad recursive
  deletion.
- Keep generated compiler, tester, cache, log, and runtime churn out of commits
  unless the release/evidence contract explicitly requires the artifact.

## Best-quality coding contract

“Best quality” means all applicable rules below are satisfied and evidenced.
It does not mean writing the largest abstraction or claiming that tests are
probably sufficient.

### Every code change

- State one semantic concern and the affected scope: `SHARED`, `GOLDI`,
  `GOLDM`, or `CROSS_PROFILE`.
- Identify regression risks and tests before editing.
- Read the current implementation, its callers, configs, and tests completely
  enough to understand the behavior being changed.
- Keep patches small, reversible, and reviewable. Do not mix strategy tuning,
  refactoring, deployment, and UI work in one batch.
- Use explicit types and domain models at boundaries. Avoid unstructured dicts
  for new durable strategy, execution, or event contracts.
- Validate inputs once at the boundary and preserve invariants internally.
- Make time, timezone, profile, symbol, account, and event identity explicit.
- Inject clocks and external adapters for deterministic tests.
- Use causal closed-bar availability. Forming bars and future information may
  not enter a confirmation decision.
- Keep hot paths bounded. No full-history scan, blocking network call, DB write,
  Telegram call, or unbounded allocation in tick-critical logic.
- Make persistence atomic, versioned, restart-safe, and idempotent.
- Use stable event/setup/order/position IDs and explicit duplicate suppression.
- Check external return codes and error states. Never swallow a broad exception
  without bounded recovery and evidence.
- Keep logs structured, sanitized, bounded, and rotated. Logs are not durable
  state.
- Do not add production `TODO`, placeholder PASS results, guessed values,
  disabled assertions, or dead compatibility branches without a removal plan.

### Python reference implementation

- Strategy rules must be pure and independent from MT5, Telegram, DB, env, and
  sleeping/polling concerns.
- Replay and incremental live feeders must call the same rules.
- Live Bear must eventually be incremental; historical replay remains a
  reference/backtest path, not the production scheduler.
- Keep adapters thin and fail closed. A unit-test fake is not E2E evidence.
- Type-check public contracts once a type checker is configured; do not silence
  errors globally.

### MQL5 implementation

- Use `#property strict` and explicit profile build contracts.
- Keep `OnTick()` minimal: tick guards, new-bar detection, and dispatch only.
- Never scan unbounded history or perform network/DB/Telegram work per tick.
- Process each closed bar exactly once and make warm-up non-tradable.
- Use profile-locked symbol/account/server/mode/magic validation in `OnInit()`
  and immediately before order submission.
- Use `CTrade`/trade requests with explicit retcode, filling, stops, freeze,
  margin, and ownership handling.
- Persist enough state for watch and open-position restart recovery without
  resurrecting stale historical orders.
- Release binaries must be reproducible, hashed, profile-specific, and tested
  on a fresh VM. Compiler success alone is not parity or E2E.

## Execution validity requirements

An executable signal contract must carry at least:

- profile and strategy version;
- setup ID and signal ID;
- setup-created and entry-ready server timestamps;
- planned entry, stop, target, risk, invalidation, and validity deadline;
- symbol tick/spread contract;
- account/server/mode/magic ownership;
- sizing and exposure limits.

Immediately before send, verify age, quote drift relative to planned risk,
spread, invalidation, account/profile binding, duplicate state, position count,
total exposure, free margin, symbol constraints, and broker check result. Do not
move structural SL/TP merely to chase the current quote. Reject stale geometry.

## Tests and evidence

Before declaring a batch PASS, run and record all applicable categories:

1. focused unit tests;
2. shared-core tests;
3. GOLD.i profile tests;
4. GOLDm profile tests;
5. cross-profile isolation tests;
6. causal/replay/incremental parity tests;
7. restart and duplicate tests;
8. execution-guard tests;
9. full regression suite;
10. external MT5/MQL5/Strategy Tester/E2E gates when required.

Record the exact command, environment, exit code, summary, and artifact path.
Do not call mocks “E2E”, an equity curve “parity”, or a compile “release
acceptance”. Price parity and event/state parity are separate assertions.

If a required external dependency is unavailable, create a reproducible
harness, record the exact prerequisite, and mark only that gate `BLOCKED`.
Never invent a PASS.

## Review priorities

Treat the following as release-blocking until disproven:

- unintended REAL order authority;
- profile/account/symbol/magic crossover;
- lookahead or forming-bar confirmation;
- stale signal or quote chasing;
- duplicate order or lost position ownership;
- restart divergence;
- Telegram/DB on the broker-critical path;
- unbounded replay, memory, disk, or notification growth;
- missing evidence for a claimed required gate.

## Progress reporting

Once the goal is active, every progress update must include:

```text
Current exact SHA:
Batch/Gate:
Affected scope: SHARED | GOLDI | GOLDM | CROSS_PROFILE
Status: IN_PROGRESS | PASS | FAIL | BLOCKED

Changed:
- ...

Tests actually run:
- command
- exit status
- result

Evidence:
- path/artifact/log

Regressions found:
- ...

Remaining gate conditions:
- ...

REAL orders:
- DISABLED
```

Never report the activated goal as complete unless every required ledger cell
and final-release artifact in `BOT-EA-CODEX-GOAL.md` is actually PASS.
