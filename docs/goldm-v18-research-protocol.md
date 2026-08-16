# GOLD.i# v1.8 Pre-Registered Research Protocol

Status: frozen before any v1.8 price-data run

Frozen on: 2026-08-15 (Asia/Bangkok)

Baseline: `GoldMSniperParity_D7_Channel12Broad.set`
Execution target during this program: demo only

## 1. Objective and non-objectives

The objective is to determine whether the frozen D7 channel-continuation baseline can be improved by:

1. direction specialization (`ALL`, `BULL_ONLY`, `BEAR_ONLY`);
2. a small, pre-declared set of candle morphologies;
3. isolated indicator-context ablations; and
4. broker-realistic R-based position management.

This program does not authorize real-account trading. It does not assume that a named candle pattern or oscillator has an edge. It does not optimize entry and exit parameters in the same search stage.

## 2. Data governance

All intervals use half-open semantics: `[from, to)`.

| Classification | Interval | Permitted use |
|---|---|---|
| Development | `[2022-02-28, 2024-02-28)` | Candidate construction, ablation, and selection |
| Locked legacy validation | `[2024-02-28, 2026-02-28)` | Previously inspected at aggregate v1.7 level; regression/corroboration only, never claimed as blind v1.8 OOS |
| Protected quarantine | `[2026-02-28, 2026-07-01)` | No read, mining, backtest, tuning, validation, OOS, or diagnostics |
| Known/exposed history | `[2026-07-01, 2026-08-12)` | Diagnostics and regression only; never candidate selection or blind OOS |
| New blind OOS | Starts no earlier than `2026-08-12` | Accumulating forward/demo evidence; not enough by date alone |

The machine-readable authority is `config/goldm-research-policy.json`. Both PowerShell runners and Python data readers must validate against it before creating output, initializing MT5, or starting a tester process.

The six fixed Development segments are not rolling or data-dependent:

| Segment | Half-open range |
|---|---|
| `D1` | `[2022-02-28, 2022-06-28)` |
| `D2` | `[2022-06-28, 2022-10-28)` |
| `D3` | `[2022-10-28, 2023-02-28)` |
| `D4` | `[2023-02-28, 2023-06-28)` |
| `D5` | `[2023-06-28, 2023-10-28)` |
| `D6` | `[2023-10-28, 2024-02-28)` |

The six locked legacy-validation segments use the same four-month cadence from
`2024-02-28` through `2026-02-28`. They may be opened only under the rule in
section 7 and must never be relabelled as blind OOS.

MetaTrader Strategy Tester treats its end date as excluded. The MT5 Python `copy_rates_range` and `copy_ticks_range` APIs treat their end timestamps as included, so Python adapters must translate an exclusive end to an inclusive API endpoint strictly below it.

### 2.1 Development warm-up is not an evaluation fold

The registered Development history envelope starts no later than `2021-01-01`.
That provides at least 200 distinct UTC history days and must reach the seven
calendar days immediately before the first evaluated timestamp. Warm-up rows
may initialize D1/H4/H1/M15/M5/M1 indicators, but they are excluded from every
selection fold, score, trade count, and Stage A metric.

For the first smoke, the identities are therefore distinct:

- history envelope: `[warmup_from, 2022-06-28)`, with
  `warmup_from <= 2021-01-01`;
- D1 evaluation: exactly `[2022-02-28, 2022-06-28)`;
- tester `FromDate=2022.02.28` and `ToDate=2022.06.28` (exclusive);
- any miner fold is a pre-registered partition wholly inside the D1 evaluation
  range. Empty, overlapping, gapped, or out-of-range fold masks are rejected.

`scripts/mine-goldm-candle-patterns.py` has no MT5/broker-history code path. It
accepts only a canonical schema-2 offline dataset manifest and a canonical,
self-hashed fold plan. The manifest must bind an independently approved source
evidence file and authority artifact. `src/goldm_signal/research_dataset.py`
independently rehashes and streams the registered CSV, verifies its exact header,
row count, first/last millisecond timestamps, monotonic ordering, half-open
bounds, warm-up coverage, custom-symbol alias, quarantine non-overlap, and source
lineage before the miner may create an output directory. Schema 1 remains
readable only for legacy inspection; miner, importer, and runner production paths
reject it.

## 3. Research environment and lineage

No matrix may run against the operator/demo terminal profile. A research run must use a dedicated terminal executable and data directory, and it must refuse to close a terminal unless that exact executable path was explicitly authorized.

Every run manifest must include:

- immutable run ID and UTC timestamps;
- Git commit and dirty-tree flag;
- EA source and compiled artifact SHA-256;
- tester preset SHA-256 and normalized input values;
- strategy ID/version, direction profile, and management-policy version;
- terminal executable/version, data directory, broker server, symbol specification, and history coverage;
- test model, execution delay, deposit, leverage, currency, spread/commission/swap assumptions;
- declared purpose and exact half-open range;
- compile result and report/log hashes;
- every candidate outcome, including failures and zero-trade runs.

A performance line is accepted only if it contains the current run ID. Reading the last line of a shared tester log without run correlation is prohibited.

### 3.1 Online tester history is prohibited

A fresh online Strategy Tester is not a safe way to request D1. MetaQuotes
documents that the tester synchronizes symbol history and, on the first request,
downloads the available history before providing the requested test interval.
An online launch can therefore read the protected quarantine even when the INI
contains a safe D1 date range. `UseRemote=0`, `UseCloud=0`, and a safe
`FromDate`/`ToDate` do not prevent that initial broker-history synchronization.

Every v1.8 tester run must use a broker-name-distinct custom alias such as
`GOLD_i_DEV_SAFE`; the broker source remains `GOLD.i#` only in provenance. Both
the tester `Symbol` and EA `InpExpectedSymbol` must equal the custom alias. A
custom symbol with the broker's exact name is prohibited because MetaQuotes may
delete it when a same-named server symbol is encountered.

### 3.2 Bounded offline dataset contract

The guarded export is a separate, deliberately authorized operation. It may
export only the declared warm-up plus Development envelope and must stop before
the exclusive end. It produces:

1. UTF-8 `MT5_TICKS_CSV_V1` with exact columns
   `time_msc,bid,ask,last,volume,flags,volume_real`;
2. a schema-2 manifest with dataset ID, purpose/classification,
   custom/source symbols, warm-up and evaluation boundaries, exact row count,
   first/last `time_msc`, CSV path/hash, approved source-evidence path/hash, and
   self-hash;
3. a raw demo symbol-specification capture and its SHA-256;
4. a raw demo broker-cost source and its SHA-256; and
5. an import receipt/inventory binding the custom-symbol cache back to those
   artifacts.

The importer must configure all price-sensitive symbol properties before price
history is inserted. MetaQuotes warns that changing digits, point, tick size or
value, chart mode, or formula after import deletes custom-symbol history. The
approved implementation path is `CustomSymbolCreate`, exact property/session
configuration, then `CustomTicksReplace` (or `CustomRatesReplace` only for a
separately declared bar-model experiment). The custom symbol must have no
formula or live origin dependency.

`copy_rates_range` + `CustomRatesReplace` is technically feasible without
Administrator rights for an isolated bar-model/report-parser smoke, but it is
not evidence for Stage A's real-tick model: the tester must synthesize intrabar
ticks. Stage A requires an exact bounded `copy_ticks_range` export and
`CustomTicksReplace`. These experiment classes must never be compared or
silently substituted.

An exact Python range limits rows returned to the exporter; it does not by
itself prove that an online standard terminal did not synchronize additional
broker history internally. Therefore the guarded export is also `NO-GO` on an
online, non-isolated source terminal. It needs an offline/cache proof whose safe
contents are already known, enforceable source-terminal network isolation, or a
trusted external source that guarantees the requested half-open range. The
export guard must run before terminal initialization and translate the exclusive
end to an inclusive API endpoint strictly below it.

Registration does not create or self-approve provenance. It consumes a
pre-existing schema-1 source-evidence file whose complete-file SHA-256 was
approved through a separate trust channel. That evidence binds the original
tick bytes, exact safe range, source symbol, capture method, authority, and an
independent authority artifact. Registration copies the approved bytes to a new
exclusive destination, streams all rows without retaining a multi-year tick set
in memory, and emits a schema-2 manifest:

```powershell
python scripts/register-goldm-research-dataset.py `
  --source-evidence C:\absolute\approved\d1-source-evidence.json `
  --expected-source-evidence-sha256 <out-of-band-approved-lowercase-sha256> `
  --destination-dataset C:\ProgramData\goldm-research\d1-ticks.csv `
  --manifest C:\ProgramData\goldm-research\d1-dataset.json `
  --dataset-id goldm-stagea-d1-ticks-v1 `
  --custom-symbol GOLD_i_DEV_D1
```

The current machine has no approved source-evidence file or tick CSV. Therefore
this command must not be run yet; the example defines the later controlled
registration step, not authorization to inspect broker caches.

No actual import has yet been performed for this program. Until an importer
receipt and a post-import custom-cache inventory are available, execution is
`NO-GO`; a manifest alone is not proof that MT5 is testing the registered CSV.

The importer implementation is now split into three fail-closed components:

- `src/goldm_signal/research_import.py` validates a self-hashed symbol
  specification, exact tick dataset, portable clone inventory, and independently
  sealed network-isolation evidence before staging anything;
- `mt5/Scripts/bot-ea/ImportGoldMOfflineTicks.mq5` refuses connected/non-portable
  terminals, creates the alias with no origin, configures every registered
  property/session before history, imports ordered ticks with
  `CustomTicksReplace`, reads them back with `CopyTicksRange`, and writes a raw
  receipt only after an exact cache comparison; and
- the Python sealer requires the exact terminal to be stopped, re-hashes all
  source/control files, validates the raw receipt, rejects broker/account state,
  and seals hashes of every file under `bases/Custom`.

The MQL5 script does not attempt to hold a multi-year CSV in memory. It imports
bounded chunks and never splits ticks sharing the same `time_msc`; the independent
readback comparison is day-bounded. The freshly recreated symbol plus full-day
comparison prevents stale or extra ticks from being silently accepted.

Preparation is intentionally non-executing:

```powershell
python scripts/prepare-goldm-offline-import.py prepare `
  --dataset-manifest C:\absolute\research\d1-dataset.json `
  --symbol-spec C:\absolute\research\d1-symbol-spec.json `
  --terminal-root C:\ProgramData\goldm-mt5-research-portable-6090 `
  --network-isolation-evidence C:\ProgramData\goldm-mt5-research-portable-6090\network-isolation-evidence.json `
  --clone-manifest C:\ProgramData\goldm-mt5-research-portable-6090\portable-clone-manifest.json `
  --expected-signer-thumbprint 5A64A7AED24C33DED342D01D01FA5286F06DA6DC `
  --expected-file-version 5.0.0.6090 `
  --import-id goldm-stagea-d1-import-0001 `
  --from-date 2022-02-28 `
  --to-date 2022-06-28 `
  --purpose Development `
  --statistical-classification DEVELOPMENT_SELECTION
```

After an operator has run the compiled importer in the exact offline clone and
the exact terminal plus all scoped MetaTester processes are stopped, seal the
receipt without launching MT5:

```powershell
python scripts/prepare-goldm-offline-import.py seal `
  --import-plan C:\absolute\mt5-research-portable\MQL5\Files\goldm_research\goldm-stagea-d1-import-0001\import-plan.json `
  --output C:\absolute\research\goldm-stagea-d1-import-receipt.json `
  --clone-manifest C:\ProgramData\goldm-mt5-research-portable-6090\portable-clone-manifest.json `
  --expected-signer-thumbprint 5A64A7AED24C33DED342D01D01FA5286F06DA6DC `
  --expected-file-version 5.0.0.6090
```

Research execution then requires provenance `schema_version: 3` with exact
`custom_symbol_import.receipt_path` and `receipt_sha256`. Schema 2 remains
loadable only for read-only legacy inspection; `MT5ResearchRunner.run()` rejects
it before staging tester inputs or launching the terminal.

### 3.3 Portable clone requirements

The research terminal is a writable portable clone outside `Program Files` and
outside the operator profile. Its provenance must bind the exact build and
SHA-256 of `terminal64.exe`, `metaeditor64.exe`, and `metatester64.exe`.

The clone is assembled from clean installation files only. It must never copy
the operator's `%APPDATA%\MetaQuotes\Terminal` tree. Before import it contains no
`Config\accounts.dat`, broker account/profile, broker server history, tester
cache, report, or log. After import, the only price store permitted is the
sealed custom-symbol store under `bases\Custom`; `bases\<broker-server>` is
forbidden. Launch uses the exact cloned `terminal64.exe` with `/portable`, so
the installation and data directory are identical.

The non-executing assembler requires an externally supplied MetaQuotes signer
thumbprint and exact four-part build. It copies only the three signed binaries,
creates the staging leaf atomically with a protected DACL limited to the current
user, SYSTEM, and Administrators, publishes by same-volume rename, and writes a
self-hashed schema-2 manifest. The destination must be on NTFS; FAT/exFAT is
prohibited because it cannot preserve the required DACL. Verification after
assembly is bound to the sealed clone and does not depend on a mutable source
installation remaining unchanged.

Current clean-clone evidence (assembled without launching any binary):

- root: `C:\ProgramData\goldm-mt5-research-portable-6090`;
- build: `5.0.0.6090`;
- signer thumbprint: `5A64A7AED24C33DED342D01D01FA5286F06DA6DC`;
- manifest file SHA-256:
  `10a8ae81ac6bda98d4e343b39936928565032f1c9924c708fe8adbf8e5773de6`;
- manifest payload SHA-256:
  `adef6cbb8aeedd08f415d8c8780ac43bb2d265cc58bd6077e0b005e7af4715fe`.

This evidence proves only clean assembly and ACL/signature/build identity. It
does not authorize launching MetaEditor, the importer, MetaTester, or terminal.

Before any research binary is launched, an elevated operator must install and
seal three exact ActiveStore outbound `Block` rules. The command refuses
pre-existing/ambiguous names, rolls back only rules created by its own failed
attempt, and stores evidence only inside the private clone root:

```powershell
python scripts/secure-goldm-research-network.py install `
  --clone-manifest C:\ProgramData\goldm-mt5-research-portable-6090\portable-clone-manifest.json `
  --expected-signer-thumbprint 5A64A7AED24C33DED342D01D01FA5286F06DA6DC `
  --expected-file-version 5.0.0.6090 `
  --evidence C:\ProgramData\goldm-mt5-research-portable-6090\network-isolation-evidence.json
```

`prepare`, `seal`, runner preflight, immediately-before-launch, and
immediately-after-exit all re-probe ActiveStore. A schema-1/self-asserted JSON
cannot satisfy these live execution gates.

EA source is compiled for that clone, with a zero-error/zero-warning compile log
and source/binary/log hashes. The EX5 and per-run set are staged only under that
clone. Static tester INIs are prohibited; the runner generates a run-ID-bound
INI only after all read-only guards pass.

OS-level outbound blocking for the cloned terminal/tester is the strongest
isolation and remains required for a production-quality smoke unless the sealed
custom-only root and importer/post-run scan can independently prove that no
broker history path existed. On the current host the user is not an
Administrator and Windows Sandbox is unavailable, so such isolation has not
been established. This is an external `NO-GO` blocker, not a condition that a
JSON assertion may waive.

### 3.4 Pre-run declarations versus post-run observations

Pre-run provenance binds only facts knowable before execution: repository and
EA identity, compile evidence, set values, custom/source symbol specification,
dataset/manifest hashes and bounds, network/import evidence, broker-cost source,
requested period, and tester settings. It does not declare expected Bars or
Ticks by copying values from a future report.

After MT5 exits, the strict `MT5_STRATEGY_TEST_HTML_EN_V1` contract parses the
actual HTML table and records its symbol, period, broker, history quality, Bars,
and Ticks as `history_observation`. Report and append-only log hashes are then
bound into the verified manifest. Missing, localized, stale, structurally
different, or identity-mismatched HTML fails closed. Before a matrix, only the
registered A0/D1 smoke may establish that the installed build's real GoldM HTML
matches this contract.

### 3.5 A0 baseline artifact rule

A rerun of current A0 can demonstrate determinism, but it cannot establish
parity with the historical D7 implementation. A valid A0 baseline is immutable,
trade-level legacy telemetry on the identical safe dataset and contains setup
ID, side, entry, exit reason, total R, R1/R2/R3, MFE, and MAE. Existing aggregate
v1.7 documents and `.tst` summaries are insufficient to reconstruct those rows.

If legacy trade-level telemetry cannot be reconstructed without using protected
data, Stage A remains blocked as `BASELINE_ARTIFACTS_MISSING`; no aggregate-to-
trade synthetic baseline may be fabricated.

### 3.6 Registered A0/D1 smoke and recovery

The default command is read-only and writes nothing:

```powershell
python scripts/run-goldm-research-safe.py `
  --stage-a-plan C:\absolute\research\stage-a-plan.json `
  --clone-manifest C:\ProgramData\goldm-mt5-research-portable-6090\portable-clone-manifest.json `
  --expected-signer-thumbprint 5A64A7AED24C33DED342D01D01FA5286F06DA6DC `
  --expected-file-version 5.0.0.6090 `
  --preflight
```

Only after every `GO` item below is independently satisfied may the full 3x6
plan be registered while executing one cell:

```powershell
python scripts/run-goldm-research-safe.py `
  --stage-a-plan C:\absolute\research\stage-a-plan.json `
  --registry C:\absolute\research\stage-a.registry.jsonl `
  --clone-manifest C:\ProgramData\goldm-mt5-research-portable-6090\portable-clone-manifest.json `
  --expected-signer-thumbprint 5A64A7AED24C33DED342D01D01FA5286F06DA6DC `
  --expected-file-version 5.0.0.6090 `
  --execute-smoke-a0-d1
```

This creates 18 immutable `PLANNED` records, then `STARTED` and `COMPLETED` only
for A0/D1; the other 17 remain `PLANNED`. Repeating the smoke returns the
hash-bound completed manifest and does not relaunch. A later full `--execute`
resumes the remaining cells and does not rerun A0/D1.

If the process crashes after `STARTED`, do not retry the run ID. After manually
proving the exact terminal path and data path are stopped, reconcile only:

```powershell
python scripts/run-goldm-research-safe.py `
  --stage-a-plan C:\absolute\research\stage-a-plan.json `
  --registry C:\absolute\research\stage-a.registry.jsonl `
  --recover-smoke-a0-d1
```

Recovery never starts, closes, terminates, or retries MT5.

### 3.7 Current executable decision

| Check | Current status |
|---|---|
| Exact D1 half-open dates and registered folds | GO in tooling/tests |
| Online broker-history path removed from candle miner | GO in tooling/tests |
| Dataset v2 source evidence, CSV/manifest hash, row, timestamp, warm-up, alias, and quarantine guards | GO in tooling/tests; actual approved source/ticks absent |
| Non-circular declared-vs-observed report provenance | GO in tooling/tests |
| Broker-cost source path/hash contract | GO in tooling/tests; real evidence absent |
| Registered partial A0/D1 execution, idempotent resume, stopped-only recovery | GO in tooling/tests |
| Actual clean portable clone | GO: signed build 6090 clone + private ACL + sealed manifest; never launched |
| Matching newly compiled EX5 inside clone | NO-GO: absent; MetaEditor launch not authorized yet |
| Importer, readback comparison, receipt sealer, and runner binding | GO in tooling/tests; no MT5 launch |
| Actual custom-symbol import receipt/cache inventory | NO-GO: absent |
| Enforceable network isolation or equivalent sealed-root proof | Tooling/live gates GO; actual rules/evidence NO-GO because current process is non-elevated |
| Actual GoldM English HTML report fixture/contract smoke | NO-GO: not run |
| Historical trade-level A0 baseline | NO-GO: absent |

The current overall decision is therefore **NO-GO FOR MT5 LAUNCH**. No price
history, custom-symbol import, terminal launch, or backtest is authorized merely
by passing the Python tests.

## 4. Frozen baseline and identity

`C0_D7_CHANNEL_CONT_ALL_M1` is the control:

- entry logic and every existing D7 parameter are unchanged;
- direction profile is `ALL`;
- partial close is disabled;
- R1 protection target is `+0.25R`;
- R2 protection target is `+1.00R`;
- R3 policy is full close;
- one strategy/profile executor is active per execution account.

`ALL` is a router/profile, not a third algorithm that runs beside BULL and BEAR. Running `ALL`, `BULL_ONLY`, and `BEAR_ONLY` simultaneously on one account would duplicate signals and is prohibited.

Executable `BULL_ONLY` and `BEAR_ONLY` runs need not sum to `ALL`, because the EA currently has one active setup state. Disabling one direction can free state for a later setup in the other direction. Reports must distinguish:

- attribution: BUY/SELL subsets of the same `ALL` run; and
- executable profiles: independent reruns with one direction disabled.

## 5. Candidate budget

### Stage A — parity and direction

| ID | Entry family | Direction | Management |
|---|---|---|---|
| `A0` | Frozen D7 channel continuation | ALL | Existing model M1 |
| `A1` | Frozen D7 channel continuation | BULL_ONLY | Existing model M1 |
| `A2` | Frozen D7 channel continuation | BEAR_ONLY | Existing model M1 |

The new EA in `A0` must reproduce the prior baseline's setup IDs, side, entry, exit reason, total trades, total R, R1/R2/R3 counts, MFE, and MAE on identical safe development segments. A direction-only code change is rejected if parity fails.

### Stage B — morphology, no new oscillator tuning

| ID | Morphology | Required context |
|---|---|---|
| `B0` | D7 channel continuation control | Frozen D7 context |
| `B1` | Channel breakout then retest continuation | Prior channel break, bounded retest, continuation confirmation |
| `B2` | Morning/Evening Star reversal | Numeric three-candle definition, prior directional move, structure location, confirmation |
| `B3` | Bullish/Bearish engulfing reversal | Numeric body engulfment, minimum body/range, structure location, confirmation |
| `B4` | Wick-rejection reversal | Wick/body and close-location ratios, structure location, confirmation |

A standalone doji is never an entry signal. Morning Doji Star and Evening Doji Star are variants inside `B2`, not extra unreported trials. Bullish and bearish definitions must be mirrors unless an asymmetry is declared before a run.

### Stage C — isolated filter ablations

Only morphology parents that pass Stage B may enter Stage C.

| ID | Filter |
|---|---|
| `F0` | Price/structure only control |
| `F1` | Bollinger location/regime context |
| `F2` | RSI turn/slope/cross context |
| `F3` | Stochastic %K/%D extreme cross context |

RSI and Stochastic are not combined during the first filter pass. A combined filter is a separately counted trial and is allowed only if both isolated filters show stable incremental lift over the same parent.

EMA/VWAP remain regime/context classifiers; they are not counted as a fourth independent algorithm.

### Stage D — management after entry freeze

Entry logic is frozen before this stage.

| ID | Policy |
|---|---|
| `M0_STATIC` | Initial broker SL/TP only |
| `M1_R_LOCK` | R1 alert + SL `+0.25R`; R2 alert + SL `+1.00R`; R3 full close |
| `M2_RUNNER` | Same protection locks, then pre-declared runner rule |

Partial close remains off. It may become a later candidate only after trade-path MFE/MAE analysis defines a target remaining volume and demonstrates benefit independent of the entry search.

## 6. Candidate evaluation

All trials are retained in an append-only registry. A failed compile, missing report, zero-trade segment, and rejected run are results—not deletions.

Minimum development gates:

- all six development segments complete;
- at least 60 resolved trades for an ALL profile, or 30 for a single-direction profile;
- positive pooled net expectancy after modeled trading costs;
- at least four of six segments have positive expectancy;
- no single segment contributes more than 50% of total positive R;
- no unresolved manifest/hash mismatch;
- no forbidden-range access and no data-coverage substitution;
- direction and pattern telemetry agrees with the declared preset.

Ranking is not based on highest total profit alone. Reports must include:

- trade count, total/mean/median R, profit factor, win rate, payoff ratio;
- maximum drawdown in R and cash, maximum loss streak, time under water;
- R1/R2/R3 reach rates, MFE/MAE, holding time, and exit reason;
- BUY and SELL attribution separately;
- segment dispersion and concentration;
- spread, slippage, commission, and swap sensitivity;
- block-bootstrap confidence intervals;
- multiplicity diagnostics (White Reality Check or SPA where applicable, PBO, and Deflated Sharpe Ratio).

The canonical trade-level scorer joins `SNIPER_SIGNAL` and `SNIPER_OUTCOME` by
both `runId` and setup ID. It rejects interleaved run IDs, duplicates, orphaned
events, direction leakage, non-monotonic R flags, and disagreement with
`SNIPER_PERFORMANCE`. Profit factor with no losing observations is recorded as
undefined rather than serialized as infinity. Additional cost stress is reported
separately as an explicitly declared R deduction per resolved trade; it is never
silently folded into the raw model result.

For a child filter to replace its parent, it must improve the pre-declared primary metric on at least four of six development segments and must not worsen the pooled maximum drawdown by more than 10%. If no candidate clears the gates, the outcome is `NO PROMOTION`.

## 7. Locked validation and honest OOS rule

Aggregate D5/D7 results from `[2024-02-28, 2026-02-28)` were already inspected during v1.7 work. The interval therefore remains locked, but it is not statistically blind for v1.8. No v1.8 threshold or candidate may be selected, repaired, or re-ranked from this interval.

At most two already-frozen finalists per research family may be run there once as a labelled corroborative regression. Candidate code, preset, metric definitions, and ranking order are hashed first. A result from this interval must be labelled `LOCKED_LEGACY_VALIDATION`, never `BLIND_OOS`.

Validation is pass/fail; it is not a new tuning set. A validation failure cannot be repaired by changing thresholds and rerunning the same validation as if it were still unseen. Any exploratory follow-up is labelled post-validation analysis and cannot claim confirmatory status.

Until enough observations accumulate strictly after `2026-08-12`, candidate selection relies on nested/segmented development evidence and the final conclusion must explicitly say that a new blind OOS result is not yet available.

Minimum validation gates mirror development and additionally require:

- positive pooled expectancy;
- at least four of six positive segments;
- no material deterioration in cost sensitivity;
- no direction/profile invariant violation;
- no unexplained parity or lifecycle divergence.

## 8. Broker-realistic lifecycle requirements

The broker R denominator is frozen per filled position:

`initial_risk_distance = abs(actual_broker_entry - broker_confirmed_initial_stop)`

It is never recomputed from a trailed stop. Current R uses executable prices:

- BUY: `(Bid - actual_entry) / initial_risk_distance`
- SELL: `(actual_entry - Ask) / initial_risk_distance`

Milestone reach and broker-action confirmation are separate states. An alert must distinguish `REACHED`, `PROTECTION_CONFIRMED`, `PROTECTION_FAILED`, and `CLOSE_CONFIRMED`.

Broker mutations are idempotent and postcondition-verified. A direct gap to R2 records R1 and R2 but submits only the R2 stop. A direct gap to R3 prioritizes full close. A more protective manual/broker stop is never loosened. Ambiguous modify/close responses enter `UNKNOWN` and are reconciled before retry.

Stopping new entries must not stop management of already-open positions.

## 9. Required verification before deployment

1. Full Python suite passes.
2. EA compiles with zero errors and zero warnings.
3. Static and runtime quarantine tests pass.
4. Legacy database migration and idempotent re-initialization pass.
5. Concurrent action-claim and crash-recovery tests pass.
6. Adapter SL/TP request and postcondition tests pass.
7. Direction/profile parity tests pass.
8. Development matrix gates pass.
9. Frozen validation passes once under the pre-registered rule.
10. Demo forward soak shows no duplicate entry, duplicate partial/close, unmanaged position, or model/broker divergence.

Only after all gates pass may the demo VM be updated. Real-account mode remains separately gated and disabled.

## 10. Evidence basis

The candidate budget reflects mixed primary evidence rather than assuming indicator profitability:

- Marshall, Young, and Rose (2006), candlestick rules on DJIA: <https://doi.org/10.1016/j.jbankfin.2005.08.001>
- Horton (2009), candlestick predictive value: <https://doi.org/10.1016/j.qref.2007.10.005>
- Fock, Klein, and Zwergel (2005), intraday futures candlesticks: <https://doi.org/10.3905/jod.2005.580514>
- Lu, Chen, and Hsu (2015), reversal patterns and holding policy: <https://doi.org/10.1016/j.jbankfin.2015.09.009>
- Gil (2022), optimized RSI in precious metals: <https://doi.org/10.1016/j.chaos.2021.111676>
- Metghalchi et al. (2015), RSI/Stochastic and costs: <https://doi.org/10.1186/s40064-015-1334-7>
- Szakmary, Shen, and Sharma (2010), commodity-futures trend rules: <https://doi.org/10.1016/j.jbankfin.2009.08.004>
- Moskowitz, Ooi, and Pedersen (2012), time-series momentum: <https://doi.org/10.1016/j.jfineco.2011.11.003>
- Batten et al. (2018), intraday gold technical trading: <https://doi.org/10.1016/j.intfin.2017.06.005>
- Gold intraday robustness follow-up (2022): <https://doi.org/10.1016/j.intfin.2021.101481>
- White (2000), Reality Check: <https://doi.org/10.1111/1468-0262.00152>
- Bailey et al., Probability of Backtest Overfitting: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253>
- Bailey and López de Prado, Deflated Sharpe Ratio: <https://doi.org/10.3905/jpm.2014.40.5.094>
- Official MT5 tester interval semantics: <https://www.metatrader5.com/en/terminal/help/algotrading/testing>
- Official MT5 tester history synchronization behavior: <https://www.metatrader5.com/en/terminal/help/algotrading/test_preparation>
- Official terminal `/portable`, `/config`, and startup configuration: <https://www.metatrader5.com/en/terminal/help/start_advanced/start>
- Official terminal file/data-directory structure: <https://www.metatrader5.com/en/terminal/help/start_advanced/structure>
- Official custom-symbol storage, import, and Strategy Tester support: <https://www.metatrader5.com/en/terminal/help/trading_advanced/custom_instruments>
- Official `CustomSymbolCreate`/custom-symbol API index: <https://www.mql5.com/en/docs/customsymbols>
- Official `CustomTicksReplace` contract: <https://www.mql5.com/en/docs/customsymbols/customticksreplace>
- Official custom-symbol property mutation contracts: <https://www.mql5.com/en/docs/customsymbols/customsymbolsetinteger> and <https://www.mql5.com/en/docs/customsymbols/customsymbolsetdouble>
- Official custom-symbol trading-session contract: <https://www.mql5.com/en/docs/customsymbols/customsymbolsetsessiontrade>
- Official `MqlTick` structure and post-import tick reader: <https://www.mql5.com/en/docs/constants/structures/mqltick> and <https://www.mql5.com/en/docs/series/copyticksrange>
- Official MQL5 file sandbox and SHA-256 primitive: <https://www.mql5.com/en/docs/files/fileopen> and <https://www.mql5.com/en/docs/common/cryptencode>
- Official MT5 inclusive Python rates endpoint: <https://www.mql5.com/en/docs/python_metatrader5/mt5copyratesrange_py>
