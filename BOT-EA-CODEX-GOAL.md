---
goal_id: BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E
goal_status: ACTIVE
authority: AUTHORITATIVE_CODEX_GOAL
target_repository: badaruddinl/bot-ea
target_branch: feature/global-orchestrator
baseline_commit: b042d51cfc3b2ea1f9aa048054af03d79d79726e
shared_engine_target: MQL5
reference_engine_target: PYTHON
deployment_profiles:
  - GOLDI
  - GOLDM
production_real_orders_default: DISABLED
completion_requires_all_required_gates_pass: true
completion_requires_full_e2e: true
completion_requires_fresh_vm_acceptance: true
---

# /goal — BOT-EA Live Engine Native Real-Time, Dual Profile GOLD.i/GOLDm, Parity, E2E, dan Final `.ex5`

```text
/goal

Kerjakan exact remote tip repository badaruddinl/bot-ea branch
feature/global-orchestrator sampai live trading engine menjadi stateful,
incremental, causal, fail-closed, dan native real-time di EA MQL5.

Pertahankan satu shared strategy core, tetapi perlakukan GOLD.i dan GOLDm
sebagai dua deployment profile yang berbeda dan tidak boleh tercampur.
Masing-masing profile wajib mempunyai config fingerprint, symbol binding,
account/trade-mode binding, sizing, risk limits, magic number, state,
audit, event routing, backtest corpus, parity report, E2E report, fresh-VM
acceptance, dan binary release sendiri.

Target release konservatif:

- GoldEngine-GOLDi-vX.Y.Z.ex5
- GoldEngine-GOLDm-vX.Y.Z.ex5

Kedua binary dibangun dari shared engine source yang sama, tetapi setiap
binary harus profile-locked dan fail closed bila dipasang pada symbol,
account, server, atau trade mode yang tidak sesuai. Pada VM tujuan, engine
trading harus dapat dijalankan hanya dengan MetaTrader 5 dan satu binary
.ex5 yang sesuai dengan profile tersebut. Database dan Telegram ditangani
oleh bridge non-critical; bridge mati tidak boleh menghentikan trading EA.

Jangan berhenti pada refactor Python, unit test, backtest, compile MQL5,
shadow mode, DEMO smoke, atau dokumentasi. Goal hanya selesai setelah
seluruh required gate di dokumen ini PASS untuk shared core, GOLD.i,
GOLDm, cross-profile isolation, full E2E, failure/restart recovery,
resource/storage stability, fresh-VM acceptance, dan release evidence.

Tidak ada completion berdasarkan waktu, jumlah commit, jumlah batch,
persentase progres, atau klaim "sebagian besar selesai". Jika gate gagal,
perbaiki sampai PASS. Status BLOCKED bukan DONE.

Jangan melakukan tuning strategi selama migrasi arsitektur kecuali ada
bug semantics yang dibuktikan dengan test dan evidence. Python tetap
menjadi reference/backtest implementation sampai parity MQL5
tersertifikasi. Production trading decision, order execution, dan
position management akhirnya harus berjalan langsung di EA/MT5.

Repository tidak memiliki product UI desktop, Qt/Tk app, atau WebSocket
service. Operational control tetap melalui MT5, worker/orchestrator, audit, dan
Telegram bridge yang non-critical.

Agent tidak boleh mengaktifkan REAL order tanpa otorisasi eksplisit
manusia. Semua engineering gate harus diselesaikan melalui unit,
historical replay, deterministic parity, MT5 Strategy Tester, shadow,
dan live DEMO. GOLDm production profile tetap disiapkan dan divalidasi
secara fail-closed, sedangkan aktivasi REAL merupakan tindakan manusia.
```

---

# 1. Kedudukan Dokumen

Dokumen ini adalah:

- `/goal` utama bagi agent Codex;
- pedoman implementasi dari source sekarang sampai final release;
- kontrak arsitektur;
- kontrak dual-profile;
- urutan batch dan gate;
- test matrix;
- evidence contract;
- definition of done.

Dokumen ini bukan:

- roadmap berbasis kalender;
- kalender pengerjaan;
- daftar saran opsional;
- izin untuk melewati test eksternal;
- izin untuk menyebut compile sebagai selesai;
- izin untuk menyatukan GOLD.i dan GOLDm menjadi satu config;
- izin untuk mengaktifkan akun REAL secara otomatis.

Jika README, komentar, config lama, atau source lama bertentangan dengan target ini, agent harus:

1. memeriksa exact current source;
2. merekam current behavior;
3. menjaga regression evidence;
4. memperbaiki secara batch kecil;
5. tidak mengubah strategi diam-diam;
6. tidak mengarang hasil test.

---

# 2. Makna “Konservatif”

Konservatif berarti:

```text
fail closed
small reversible changes
one semantic concern per batch
all required gates executed
no guessed evidence
no invented test result
no hidden strategy retuning
no REAL activation by agent
no cross-profile fallback
```

Konservatif tidak berarti:

```text
mengerjakan berdasarkan kalender
berhenti karena perubahan sudah banyak
menandai selesai ketika external gate belum dijalankan
mengurangi assertion agar test hijau
menunda defect P1 ke "versi berikutnya"
```

Agent harus melanjutkan goal sampai seluruh required gate benar-benar PASS.

---

# 3. Exact Baseline Wajib Ditentukan Ulang

Sebelum perubahan pertama, agent wajib mengambil exact remote tip:

```text
repository: badaruddinl/bot-ea
branch: feature/global-orchestrator
```

Rekam:

```text
commit SHA
parent SHA
tree SHA
remote branch ref
working tree clean state
CI/check status
Python version
dependency state
MetaTrader 5 version
MetaEditor/compiler version
broker/symbol contract
```

Snapshot yang terakhir dianalisis sebelum goal ini dibuat memperlihatkan file penting berikut:

```text
src/gold_portfolio/worker.py
src/gold_portfolio/mt5_session.py
src/goldm_revised/setup.py
src/goldm_revised/engine.py
src/goldm_bear/*
src/gold_orchestrator/runtime.py
config/final/orchestrator.json
config/final/goldi/*
config/final/goldm/*
tests/test_gold_portfolio_final.py
tests/test_gold_orchestrator.py
```

Nama branch bukan immutable evidence. Exact SHA yang ditemukan agent menjadi baseline resmi.

---

# 4. Dua Profile yang Tidak Boleh Digabung

## 4.1 Shared core

Bagian berikut boleh dan harus dibagi:

```text
Bar/Tick contract
timeframe scheduler
state-machine primitives
pattern primitives
ATR/EMA/SMA helpers
support/resistance primitives
psychological-level primitives
Fibonacci primitives
reason/event schema
execution guard framework
position lifecycle framework
outbox event schema
parity harness
```

Shared core tidak boleh mengetahui kredensial, audience Telegram, atau profile fallback.

## 4.2 PROFILE_GOLDI

Baseline source:

```text
config/final/goldi/worker.json
config/final/goldi/portfolio.json
config/final/goldi/revised.json
config/final/goldi/bear.json
```

Baseline semantics yang harus difingerprint ulang:

```text
group                 = goldi
symbol                = GOLD.i#
intended trade mode   = DEMO
terminal env          = GOLDI_MT5_TERMINAL_PATH
login env             = GOLDI_MT5_LOGIN
server env            = GOLDI_MT5_SERVER
magic                 = 26081911
deviation points      = 30
maximum positions     = 2
maximum total lot     = 4.0
sizing tiers          = 0.01 / 0.02 / 0.05 / 0.1 / 0.2 / 1.0 / 2.0
Telegram audience     = goldi_approved
state/audit namespace = runtime_data/final/goldi/*
Revised side          = BUY
Bear side             = SELL
```

Current source juga mempunyai pinned/source-tag contract. Agent harus mempertahankan semantics dan hash evidence sampai replacement profile manifest lulus parity.

## 4.3 PROFILE_GOLDM

Baseline source:

```text
config/final/goldm/worker.json
config/final/goldm/portfolio.json
config/final/goldm/revised.json
config/final/goldm/bear.json
```

Baseline semantics yang harus difingerprint ulang:

```text
group                 = goldm
symbol                = GOLDm#
production trade mode = REAL
terminal env          = GOLDM_REAL_MT5_TERMINAL_PATH
login env             = GOLDM_REAL_MT5_LOGIN
server env            = GOLDM_REAL_MT5_SERVER
magic                 = 26081912
deviation points      = 30
maximum positions     = 2
maximum total lot     = 200.0
sizing tiers          = 0.1 / 0.2 / 0.5 / 1.0 / 2.0 / 5.0 / 10.0 / 20.0 / 100.0
Telegram audience     = admin_only
state/audit namespace = runtime_data/final/goldm/*
Revised side          = BUY
Bear side             = SELL
```

Agent tidak boleh menyalakan REAL. Jika broker menyediakan kontrak yang setara,
live integration validation menggunakan **GOLDm safe DEMO mirror** yang terpisah
dari production profile. Broker yang digunakan tidak menyediakan GOLDm DEMO
yang semantik kontraknya setara. Karena itu jalur validasi GOLDm yang dikunci
adalah akun production REAL **read-only** untuk metadata/tick/spread/closed-bar
capture, ditambah isolated Strategy Tester untuk execution evidence. Jalur ini
tidak boleh mengimpor, memanggil, atau mengekspos order mutation API dan harus
membuktikan `orders_sent=0`; production magic/config fingerprint tetap tidak
boleh diubah diam-diam.

## 4.4 Profile isolation invariants

- GOLD.i binary tidak boleh mengelola GOLDm positions.
- GOLDm binary tidak boleh mengelola GOLD.i positions.
- Tidak ada fallback login/server dari satu profile ke profile lain.
- Tidak ada shared state file.
- Tidak ada shared magic.
- Tidak ada shared order ownership.
- GOLD.i subscriber audience tidak boleh menerima GOLDm private/REAL events.
- GOLDm admin-only event tidak boleh bocor ke GOLD.i subscriber.
- Satu profile gagal tidak boleh mematikan profile lain.
- Kedua terminal harus dapat berjalan di instalasi/path terpisah.
- Satu binary dipasang ke profile yang salah harus fail closed pada `OnInit()`.

## 4.5 Final release policy

Default release yang diwajibkan goal:

```text
GoldEngine-GOLDi-vX.Y.Z.ex5
GoldEngine-GOLDm-vX.Y.Z.ex5
```

Keduanya berasal dari shared source commit yang sama, tetapi build profile berbeda dan terkunci.

Satu generic `.ex5` dengan runtime profile selection hanya boleh menggantikan dua binary jika seluruh kondisi berikut dibuktikan:

- signed/hashed profile payload;
- no accidental default;
- wrong profile fails closed;
- full cross-profile parity;
- fresh-VM acceptance untuk kedua profile;
- tidak membutuhkan file config eksternal untuk safe startup.

Jika bukti tersebut tidak ada, tetap gunakan dua binary profile-locked.

---

# 5. Problem Statement yang Harus Ditutup

## 5.1 Polling-oriented live worker

Current model secara konseptual:

```text
run_once
sleep
run_once
```

Actual cadence mengandung waktu compute ditambah sleep dan bukan event reaction.

## 5.2 Revised sebagian stateful

Revised sudah mempunyai:

- active M5 setup;
- M1 confirmation;
- warm-up;
- state `WAIT/WATCH/ENTRY_READY/CANCELLED`.

Pertahankan semantics yang benar, lalu buktikan restart parity.

## 5.3 Bear masih replay-driven pada live path

Current live Bear masih menggunakan historical window/replay menuju NOW.

Replay tetap diperlukan untuk backtest.

Replay tidak boleh menjadi production live scheduler.

## 5.4 Execution dapat mengejar harga

Current Python execution dapat mengambil current quote dan memindahkan SL/TP berdasarkan distance dari plan lama.

Target:

```text
fresh quote
+
planned structural geometry
+
signal age
+
entry drift
+
spread
+
invalidation
```

Jika thesis tidak lagi valid:

```text
ENTRY_REJECTED
```

## 5.5 Python masih menjadi trading engine

Target final:

```text
MT5 + profile-specific .ex5
```

Python production hanya bridge.

---

# 6. Target Runtime Architecture

```text
                         BROKER
                            │
                           tick
                            ▼
       ┌───────────────────────────────┐
       │ MT5 Terminal GOLD.i           │
       │ GoldEngine-GOLDi.ex5          │
       │ profile locked: GOLDI         │
       └──────────────┬────────────────┘
                      │ events
                      │
       ┌──────────────┴────────────────┐
       │                               │
       │       Lightweight Bridge      │
       │       DB + Telegram           │
       │                               │
       └──────────────┬────────────────┘
                      │ events
       ┌──────────────┴────────────────┐
       │ MT5 Terminal GOLDm            │
       │ GoldEngine-GOLDm.ex5          │
       │ profile locked: GOLDM         │
       └───────────────────────────────┘
```

Setiap EA mempunyai:

```text
native OnTick
new-bar scheduler
bounded warm-up
stateful Revised
stateful Bear
live execution guards
CTrade execution
position management
append-only event outbox
```

Bridge tidak mempunyai authority untuk memutuskan BUY/SELL/SL/TP/CLOSE.

---

# 7. Non-Negotiable Invariants

## 7.1 Strategy

- Tidak ada online learning.
- Tidak ada automatic retuning.
- Parameter profile immutable selama release.
- Current market structure berasal dari causal market data.
- Historical live data hanya bounded warm-up.
- Bear live tidak menjalankan full replay.
- Forming bar bukan closed confirmation.
- State transition deterministic.
- Shared core tidak menghapus perbedaan profile.

## 7.2 Runtime

- Tick path tidak full-scan history.
- Tick path tidak menulis DB.
- Tick path tidak mengirim Telegram.
- Relevant bar close memicu relevant calculation.
- Tidak ada active setup menghasilkan fast return.
- Active setup tick path hanya memeriksa live conditions.
- DB/Telegram tidak berada pada broker critical path.

## 7.3 Execution

- Signal age wajib.
- Entry drift wajib.
- Spread wajib.
- Invalidation wajib.
- Account/mode/symbol/profile wajib.
- Magic/ownership wajib.
- Duplicate suppression wajib.
- Revalidation tepat sebelum send wajib.
- Stale signal tidak boleh mengejar harga.
- Reject pada satu profile tidak boleh berubah menjadi order pada profile lain.

## 7.4 Backtest/parity

Input sama menghasilkan:

```text
same profile
same setup
same side
same state transition
same reason
same planned entry
same planned SL
same planned TP
same management decision
```

Required target:

```text
event/state parity = 100%
price tolerance <= 1 symbol tick
```

Parity dihitung terpisah untuk GOLD.i dan GOLDm.

## 7.5 Release

- Exact audited source commit.
- Compiler environment dicatat.
- Binary SHA-256 dicatat.
- Profile fingerprint tertanam/terbukti.
- Fresh VM memakai binary release yang sama.
- Rollback binary tersedia.
- Semua required gate PASS.
- Tidak ada P1 terbuka.
- Tidak ada required gate `BLOCKED`.

---

# 8. Codex Operating Protocol

## 8.1 Sebelum setiap batch

- Fetch exact source.
- Baca code dan tests terkait.
- Nyatakan scope batch.
- Nyatakan profile yang terpengaruh:
  - SHARED;
  - GOLDI;
  - GOLDM;
  - CROSS_PROFILE.
- Nyatakan regression risk.
- Nyatakan test/evidence sebelum coding.
- Pastikan REAL tetap disabled.

## 8.2 Saat coding

- Satu semantic concern per batch.
- Tidak mencampur refactor dengan tuning.
- Tidak menghapus reference path sebelum parity.
- Tidak membuat fallback lintas profile.
- Tidak mengurangi assertion yang benar.
- Tidak menyembunyikan failure.
- Semua new config harus mempunyai fingerprint/version.
- Profile-neutral code harus berada di shared core.
- Profile-specific values harus berada di profile manifest/build contract.

## 8.3 Setelah coding

- Jalankan focused tests.
- Jalankan profile tests untuk GOLD.i.
- Jalankan profile tests untuk GOLDm.
- Jalankan cross-profile isolation tests.
- Jalankan regression/parity tests.
- Simpan command, output, exit code, environment.
- Review diff.
- Update gate ledger.
- Lanjut hanya jika gate batch PASS.

## 8.4 Jika dependency eksternal belum tersedia

- Jangan mengarang hasil.
- Buat reproducible harness/script.
- Tandai exact prerequisite.
- Gate tetap `BLOCKED`.
- Goal tetap `OPEN`.
- Kerjakan gate independen lain hanya jika urutannya tetap aman.
- Final completion dilarang selama required gate blocked.

## 8.5 Dilarang

- Mengganti implementation dengan kalender atau jadwal.
- Menutup goal setelah compile.
- Menutup goal setelah unit test.
- Menyebut mock sebagai E2E.
- Menyebut equity curve sebagai parity.
- Mengaktifkan REAL sendiri.
- Menghapus failing test.
- Men-tuning agar parity tampak cocok.
- Menganggap docs claim sebagai evidence.
- Menganggap satu profile PASS berarti kedua profile PASS.
- Menganggap `BLOCKED` sama dengan selesai.

---

# 9. Gate Status Ledger

Allowed status:

```text
NOT_STARTED
IN_PROGRESS
PASS
FAIL
BLOCKED
SUPERSEDED
```

Goal hanya selesai bila seluruh required cell PASS.

| Gate | Shared | GOLD.i | GOLDm | Cross-profile | Evidence |
|---|---|---|---|---|---|
| G00 Exact baseline | PASS | PASS | PASS | PASS | `evidence/G00-baseline/` |
| G01 Dual-profile fingerprints | PASS | PASS | PASS | PASS | `evidence/G01-profile-fingerprints/` |
| G02 Current behavior corpus | PASS | PASS | PASS | N/A | `evidence/G02-current-behavior-corpus/` |
| G03 Common strategy contract | PASS | N/A | N/A | PASS | `evidence/G03-common-strategy-contract/` |
| G04 Pure rule extraction | PASS | PASS | PASS | N/A | `evidence/G04-pure-rule-extraction/` |
| G05 Bear incremental parity | PASS | PASS | PASS | N/A | `evidence/G05-bear-incremental-state/` |
| G06 Revised restart parity | PASS | PASS | PASS | N/A | `evidence/G06-revised-restart-parity/` |
| G07 Event-driven reference runtime | PASS | PASS | PASS | PASS | `evidence/G07-event-driven-reference-runtime/` |
| G08 Execution validity | PASS | PASS | PASS | PASS | `evidence/G08-execution-validity/` |
| G09 Causal/tick-aware backtest | PASS | PASS | PASS | N/A | `evidence/G09-causal-tick-replay/` |
| G10A Reference market-data validation | PASS | IN_PROGRESS | IN_PROGRESS | IN_PROGRESS | `evidence/G10-reference-live-validation/` |
| G10B GOLD.i DEMO execution validation | PASS | IN_PROGRESS | N/A | N/A | `evidence/G10-reference-live-validation/` |
| G10C GOLDm tester execution validation | PASS | N/A | PASS | N/A | `evidence/G15-full-parity/` |
| G11 MQL5 runtime skeleton | PASS | PASS | PASS | PASS | `evidence/G11-mql5-runtime-skeleton/` |
| G12 Revised MQL5 parity | PASS | PASS | PASS | PASS | `evidence/G12-revised-parity/` |
| G13 Bear MQL5 parity | PASS | PASS | PASS | N/A | `evidence/G13-bear-parity/` |
| G14 EA execution lifecycle | PASS | PASS | PASS | PASS | `evidence/G14-execution-lifecycle/` |
| G15 Full parity certification | PASS | PASS | PASS | PASS | `evidence/G15-full-parity/` |
| G16 Event outbox/bridge | PASS | PASS | PASS | PASS | `evidence/G16-event-bridge/` |
| G17 Happy-path E2E | PASS | PASS | PASS | PASS | `evidence/G17-happy-path-e2e/` |
| G18 Failure/restart E2E | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | |
| G19 Resource/storage/latency | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | |
| G20 Fresh VM acceptance | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | |
| G21 Final release evidence | NOT_STARTED | NOT_STARTED | NOT_STARTED | NOT_STARTED | |

`N/A` hanya valid jika gate memang shared-only atau profile-only berdasarkan kontrak ini.

---

# 10. Batch/Gate G00 — Exact Baseline

## Objective

Membuat source awal immutable dan reproducible.

## Required work

- Resolve exact remote tip SHA.
- Record parent/tree SHA.
- Record relevant file hashes.
- Record clean checkout.
- Record CI/checks.
- Record test entrypoints.
- Record Python dependencies.
- Record MT5/MetaEditor/compiler metadata.
- Record terminal and broker metadata per profile.

## Evidence

```text
evidence/G00-baseline/
  baseline.json
  source-hashes.txt
  environment.md
  current-test-run.log
  ci-status.md
```

## PASS

- Exact SHA dapat di-checkout ulang.
- Current tests benar-benar dijalankan.
- Current failures dicatat.
- GOLD.i dan GOLDm source/config fingerprint terpisah.

---

# 11. Batch/Gate G01 — Dual-Profile Fingerprints

## Objective

Mengunci perbedaan GOLD.i dan GOLDm sebelum common-core refactor.

## Required profile manifest

```text
profile_id
strategy version
symbol
expected trade mode
terminal identity contract
account/server contract
magic
sizing tiers
max positions
max total lot
deviation
Revised config fingerprint
Bear config fingerprint
state namespace
audit namespace
Telegram audience
event privacy
```

## Required cross-profile tests

- GOLD.i manifest tidak menerima GOLDm symbol.
- GOLDm manifest tidak menerima GOLD.i symbol.
- magic berbeda.
- state/audit paths berbeda.
- terminal paths berbeda.
- audience berbeda.
- config hash swap ditolak.
- profile ID tidak boleh default kosong.

## PASS

Dua manifest immutable dapat di-hash dan tidak saling fallback.

---

# 12. Batch/Gate G02 — Current Behavior Corpus

## Objective

Merekam current semantics untuk kedua profile.

## Required scenarios per profile

### Revised BUY

- no setup;
- M5 setup;
- reinforcement;
- opposite cancellation;
- expiry;
- M1 range;
- M1 momentum;
- obstacle;
- psychological context;
- supply/demand context;
- entry-ready.

### Bear SELL

- M15 setup;
- H1 pass/reject;
- M5 touch;
- M5 rejection;
- M5 acceptance;
- M1 confirmation;
- expiry;
- entry-ready.

### Execution

- fresh quote;
- stale quote;
- drift;
- spread;
- invalidation;
- duplicate;
- max positions;
- lot normalization;
- wrong account/mode/symbol/profile;
- broker check reject;
- broker send reject;
- fill.

## Output

```text
profile_id
input fingerprint
available-at timestamp
setup_id
state transitions
decision
planned geometry
reason
execution outcome
```

## PASS

- Deterministic.
- Causal.
- Current wrong behavior tetap direkam sebagai baseline.
- Corpus GOLD.i dan GOLDm tidak tercampur.

---

# 13. Batch/Gate G03 — Common Strategy Contract

## Objective

Membuat semantic engine portable.

## Required types

```text
Bar
Tick
Timeframe
MarketSnapshot
StrategyConfig
ProfileConfig
StrategyState
SetupState
StrategyDecision
SignalPlan
PositionState
EngineEvent
```

## Required interfaces

```text
on_warmup(history)
on_bar_close(timeframe, bar)
on_tick(tick)
on_position_event(event)
```

Output:

```text
next_state
decisions
events
```

## Core must not

- access MT5;
- read env;
- sleep;
- access DB;
- call Telegram;
- send order;
- fetch unbounded history;
- infer GOLD.i/GOLDm by loose symbol substring.

## PASS

Pure in-memory engine dapat diuji dengan explicit `ProfileConfig`.

---

# 14. Batch/Gate G04 — Pure Rule Extraction

## Objective

Replay dan live menggunakan rule yang sama.

## Revised extraction

- M5 setup;
- pattern;
- range;
- momentum;
- M1 evidence;
- ATR;
- Fibonacci;
- psychological;
- S/R;
- supply/demand;
- obstacle;
- stop/target;
- invalidation.

## Bear extraction

- M15 setup;
- H1 context;
- M5 watch;
- M1 confirmation;
- stop;
- target;
- reason.

## PASS

- Old reference replay menggunakan pure rules.
- GOLD.i corpus tetap cocok.
- GOLDm corpus tetap cocok.
- Tick-size rounding mengikuti profile.

---

# 15. Batch/Gate G05 — Bear Incremental State Machine

## Objective

Menghapus full replay dari live Bear.

## State flow

```text
IDLE
→ WATCH_H1
→ WATCH_M5
→ WATCH_M1
→ ENTRY_READY
```

## Required state

```text
profile_id
setup_id
phase
setup_time
level
entry_zone
invalidation
touches
rejections
acceptance
last processed bars
evidence
```

## Required parity

```text
Bear replay
vs
Bear incremental fed bar-by-bar
```

Dilakukan terpisah untuk GOLD.i dan GOLDm.

## PASS

- Event/state parity 100%.
- Price <= 1 tick.
- No full replay pada live path.
- Bounded warm-up recovery.
- Profile-specific tick/spread/risk contract dipertahankan.

---

# 16. Batch/Gate G06 — Revised Restart Parity

## Objective

Revised tidak berubah saat restart.

## Restart points

- before setup;
- after M5 setup;
- after reinforcement;
- during M1 watch;
- before entry-ready;
- after cancel;
- with open position.

## PASS per profile

- same setup ID;
- same trigger;
- no duplicate;
- no lost setup;
- no stale resurrection;
- no historical order after warm-up.

---

# 17. Batch/Gate G07 — Event-Driven Python Reference Runtime

## Objective

Membuktikan target runtime sebelum port.

## Fast lane

```text
read tick
detect new bar
active live guards
```

## Bar lane

```text
D1/H1/M15/M5/M1 close events
```

## Slow lane

```text
health
reconciliation
event persistence
Telegram
admin
```

## Profile isolation

- separate terminal/session;
- separate engine instance;
- separate state;
- separate event namespace;
- one profile stall does not stall the other.

## PASS

- No live replay.
- No critical-path DB/Telegram.
- Event sequence matches reference feeder.
- GOLD.i and GOLDm worker isolation proven.

---

# 18. Batch/Gate G08 — Execution Validity

## Objective

Fail closed dan tidak mengejar harga.

## Required plan fields

```text
profile_id
setup_created_at
entry_ready_at
planned_entry
planned_stop
planned_target
planned_risk
valid_until
invalidation
```

## Required checks

- profile;
- age;
- drift;
- spread;
- invalidation;
- account;
- server/mode;
- symbol;
- magic;
- position count;
- total lot;
- free margin;
- broker constraints;
- duplicate.

## Drift metric

```text
abs(executable_quote - planned_entry) / planned_risk
```

Threshold versioned per profile.

## Geometry

Planned structure tidak digeser otomatis. Jika quote membuat geometry invalid, reject.

## PASS

Explicit tests lulus untuk kedua profile dan config swap ditolak.

---

# 19. Batch/Gate G09 — Causal/Tick-Aware Backtest

## Objective

Backtest menjadi regression source tanpa lookahead.

## Required

- forming bar excluded;
- M1/M5/M15/H1 availability correct;
- timezone deterministic;
- warm-up non-tradable;
- no future price;
- conservative same-bar policy;
- tick spread/intrabar path bila data tersedia;
- profile-specific symbol contract.

## PASS

- Event hash deterministic.
- Python replay dan incremental use common core.
- Separate reports untuk GOLD.i/GOLDm.

---

# 20. Batch/Gate G10 — Reference Market-Data and Execution Validation

## GOLD.i

Actual DEMO:

```text
shadow
→ guarded DEMO execution
→ position lifecycle
→ restart
```

## GOLDm

Broker tidak menyediakan akun DEMO dengan kontrak `GOLDm#` yang setara.
Gunakan profile read-only yang explicit:

```text
profile_id = GOLDM_REAL_READ_ONLY
derived_from = GOLDM_PRODUCTION_FINGERPRINT
account_mode = REAL
access_mode = READ_ONLY
orders_sent = 0
execution_evidence = ISOLATED_STRATEGY_TESTER
```

Probe REAL hanya boleh membaca account/terminal/symbol metadata, tick, spread,
dan closed bars. Order/deal/position mutation API dilarang. Strategy Tester
batch menggunakan binary profile-locked dan real ticks; tidak ada live REAL
order lifecycle pada gate engineering. Jangan mengubah GOLDm production
manifest untuk validasi.

## Cross-profile

Jalankan GOLD.i DEMO dan GOLDm read-only capture bersamaan dengan terminal/data
directory terpisah. Tidak ada GOLDm live execution lane.

## PASS

- Actual GOLD.i live DEMO evidence.
- Actual GOLDm read-only broker-data evidence dengan `orders_sent=0`.
- GOLDm isolated Strategy Tester batch evidence setelah G15.
- No duplicate.
- No state bleed.
- No privacy bleed.
- No live replay.
- Latency recorded.
- Production GOLDm order authority remains disabled.

Kontrak dan tooling fail-closed G10A membuka G11--G15. G10B dan G10C boleh
diselesaikan setelah binary MQL5 tersedia; keduanya tetap required sebelum
release acceptance.

---

# 21. Batch/Gate G11 — MQL5 Runtime Skeleton

## Objective

Native `OnTick` + new-bar scheduler.

## Structures

```cpp
Bar
Tick
ProfileConfig
StrategyState
StrategyDecision
SignalPlan
EngineEvent
ManagedPosition
```

## Scheduler

```cpp
OnTick
  detect bars
  dispatch closed D1/H1/M15/M5/M1
  if active setup: live tick checks
```

## Build profiles

```text
BUILD_PROFILE_GOLDI
BUILD_PROFILE_GOLDM
```

Setiap build menanam profile ID/fingerprint.

## PASS

- Both binaries compile.
- No full scan per tick.
- Wrong chart/profile fails `OnInit`.
- Same bar processed once.
- Warm-up no historical trade.

---

# 22. Batch/Gate G12 — Revised MQL5 Parity

## Objective

Port Revised ke shared MQL5 core.

## PASS per profile

```text
event/state = 100%
reason = exact
timestamps = exact semantic time
entry/SL/TP <= 1 profile tick
```

GOLD.i dan GOLDm masing-masing mempunyai report.

---

# 23. Batch/Gate G13 — Bear MQL5 Parity

## Objective

Port incremental Bear, bukan replay.

## PASS per profile

Sama dengan Revised plus:

- no historical full replay;
- restart parity;
- M15/H1/M5/M1 transition exact.

---

# 24. Batch/Gate G14 — EA Execution and Position Lifecycle

## Objective

EA menjadi broker authority.

## Required

- execution guards;
- CTrade request;
- retcode;
- filling/stops/freeze handling;
- position discovery;
- magic/profile ownership;
- close/modify;
- manual intervention detection;
- restart recovery.

## PASS

- Python no production order authority.
- GOLD.i EA only manages magic 26081911/profile contract.
- GOLDm EA only manages magic 26081912/profile contract.
- Bridge stopped does not stop management.
- Wrong binary/profile cannot trade.

---

# 25. Batch/Gate G15 — Full Parity Certification

## Compare

```text
Python replay
Python incremental
MQL5 harness
MT5 Strategy Tester
```

## Fields

```text
profile
event ID
setup ID
version
state
side
reason
time
planned prices
management action
```

## PASS

- Exact event parity for GOLD.i.
- Exact event parity for GOLDm.
- Price <= one symbol tick.
- Cross-profile corpus produces no cross-profile event.
- Equity curve is supplementary, not primary evidence.

---

# 26. Batch/Gate G16 — Event Outbox, Database, Telegram

## Objective

Observability non-critical.

## EA event types

```text
ENGINE_STARTED
PROFILE_VALIDATED
SETUP_CREATED
WATCH_UPDATED
WATCH_CANCELLED
ENTRY_READY
ENTRY_REJECTED
ORDER_SUBMITTED
POSITION_OPENED
POSITION_MODIFIED
POSITION_CLOSED
ENGINE_ERROR
RECOVERY_COMPLETED
```

## Delivery

```text
append-only
at-least-once
idempotent event_id
UNIQUE(event_id) in DB
ACK after persistence/delivery state
```

## Routing

- GOLD.i allowed subscriber events follow `goldi_approved`.
- GOLDm sensitive/production events are `admin_only`.
- Health/admin notifications may have explicit separate policy.
- Event carries `profile_id`.

## PASS

- DB/Telegram failure does not block EA.
- Backlog replays without duplicate DB row.
- No audience leakage.

---

# 27. Batch/Gate G17 — Full Happy-Path E2E

## GOLD.i E2E

```text
broker tick
→ GOLD.i MT5
→ GoldEngine-GOLDi
→ setup
→ confirmation
→ guards
→ DEMO order
→ position
→ close
→ outbox
→ DB
→ approved Telegram audience
```

## GOLDm E2E

Engineering E2E menggunakan safe DEMO mirror:

```text
broker tick
→ isolated GOLDm validation terminal
→ GoldEngine-GOLDm validation build/profile lock
→ setup
→ confirmation
→ guards
→ DEMO order
→ position
→ close
→ outbox
→ DB
→ admin-only Telegram
```

Exact production GOLDm binary juga wajib diuji:

- Strategy Tester;
- static fingerprint;
- refusal pada DEMO/wrong account;
- no order without matching REAL profile and human activation.

## Correlation

Satu chain ID harus menghubungkan:

```text
profile
setup
signal
order
position
event
DB row
Telegram delivery
```

## PASS

Kedua E2E lengkap dan cross-profile routing benar.

---

# 28. Batch/Gate G18 — Failure and Restart E2E

## Dependency failures

- bridge down;
- DB down;
- Telegram down;
- backlog;
- bridge recovery.

Expected: EA trading/management tetap hidup.

## MT5/broker failures

- disconnect/reconnect;
- Algo Trading off;
- wrong account;
- wrong server;
- wrong symbol;
- wrong profile;
- market closed;
- spread extreme;
- insufficient margin;
- check reject;
- send reject;
- partial/ambiguous result where supported;
- manual close/modify;
- duplicate EA instance;
- magic collision.

## Restart

- EA restart during watch;
- terminal restart;
- Windows/VM restart;
- open position recovery;
- dual terminal restart;
- one profile restart while other remains alive.

## PASS

No duplicate, no lost ownership, no cross-profile management, safe recovery.

---

# 29. Batch/Gate G19 — Resource, Storage, and Latency Stability

## Measure separately

```text
GOLD.i MT5/EA
GOLDm MT5/EA
bridge
DB
event spool
```

## Required properties

- no monotonic RAM leak;
- bounded warm-up memory;
- no full-history allocation loop;
- no per-tick DB growth;
- spool bounded/rotated without dropping unacknowledged trade events;
- one profile load does not starve the other;
- latency metrics recorded.

## Metrics

```text
bar close → detection
detection → decision
entry ready → submit
submit → broker ack
event enqueue → DB
event enqueue → Telegram
```

## PASS

Evidence shows stable resource trend and no hidden replay/notification stall.

Tidak ada fixed RAM angka yang boleh dikarang. Baseline dan trend menjadi evidence.

---

# 30. Batch/Gate G20 — Fresh VM Acceptance

## GOLD.i VM

```text
install MT5
login correct DEMO
copy GoldEngine-GOLDi-vX.Y.Z.ex5
attach correct chart
enable Algo Trading
validate profile
warm-up
smoke/E2E
restart/recovery
```

## GOLDm VM

```text
install separate MT5
prepare correct account environment
copy GoldEngine-GOLDm-vX.Y.Z.ex5
attach correct chart
verify fail-closed bindings
Strategy Tester / safe validation
no REAL activation by agent
restart/recovery
```

## Single-file deployment rule

Engine must not require:

```text
Python strategy runtime
research DB
source .mq5
external model
30-day cache
external strategy JSON
```

Bridge may be separate and optional for trading continuity.

## PASS

Each VM needs only the relevant `.ex5` for engine operation and wrong-profile installation fails closed.

---

# 31. Batch/Gate G21 — Final Release Evidence

## Required binaries

```text
GoldEngine-GOLDi-vX.Y.Z.ex5
GoldEngine-GOLDm-vX.Y.Z.ex5
```

## Required release tree

```text
release/
  GoldEngine-GOLDi-vX.Y.Z.ex5
  GoldEngine-GOLDm-vX.Y.Z.ex5
  SHA256SUMS.txt
  source-commit.txt
  build-environment.md
  profile-GOLDI-manifest.json
  profile-GOLDM-manifest.json
  parity-GOLDI.md
  parity-GOLDM.md
  e2e-GOLDI.md
  e2e-GOLDM.md
  cross-profile-isolation.md
  failure-recovery.md
  resource-storage-latency.md
  fresh-vm-GOLDI.md
  fresh-vm-GOLDM.md
  known-limitations.md
  rollback.md
```

## PASS

- Binary hashes match fresh-VM binaries.
- Both profile manifests match embedded/build fingerprints.
- All gate evidence linked.
- No P1.
- No required blocked gate.
- REAL activation state remains explicit and human-controlled.

---

# 32. Required CI / Validation Commands

Repository harus menyediakan equivalent gates:

```text
validate-unit
validate-profile-contracts
validate-causality
validate-replay
validate-incremental
validate-execution-guards
validate-python-parity
validate-mql5-build
validate-mql5-parity-goldi
validate-mql5-parity-goldm
validate-cross-profile
validate-event-contract
validate-e2e
validate-release
```

`validate-release` wajib bergantung pada seluruh gate required sebelumnya.

## Mutation tests yang direkomendasikan

CI harus gagal bila:

- symbol GOLD.i/GOLDm ditukar;
- magic ditukar;
- audience ditukar;
- account mode ditukar;
- config hash dimutasi;
- future bar disuntikkan;
- live Bear kembali memanggil replay;
- signal-age guard dihapus;
- drift guard dihapus;
- invalidation guard dihapus;
- DB/Telegram dipindahkan ke critical path;
- MQL5/Python reason divergen;
- one-tick tolerance dilampaui;
- wrong profile tidak fail closed.

---

# 33. E2E Acceptance Matrix

| Scenario | GOLD.i | GOLDm | Cross-profile |
|---|---|---|---|
| Setup → watch → entry | Required PASS | Required PASS | No contamination |
| Setup → cancel | Required PASS | Required PASS | No contamination |
| Fresh guarded order | Required PASS | Required PASS via isolated Strategy Tester; no live REAL claim | Correct profile |
| Stale reject | Required PASS | Required PASS | Correct profile |
| Drift reject | Required PASS | Required PASS | Correct profile |
| Spread reject | Required PASS | Required PASS | Correct profile |
| Invalidation reject | Required PASS | Required PASS | Correct profile |
| Position lifecycle | Required PASS | Required PASS | Own magic only |
| Restart watch | Required PASS | Required PASS | Independent |
| Restart open position | Required PASS | Required PASS | Own magic only |
| Bridge down | Trading continues | Trading continues | Independent queues |
| DB down | Trading continues | Trading continues | Profile IDs intact |
| Telegram down | Trading continues | Trading continues | Privacy intact |
| Wrong symbol | Fail closed | Fail closed | No fallback |
| Wrong account/mode | Fail closed | Fail closed | No fallback |
| Wrong binary | Fail closed | Fail closed | Required |
| Fresh VM | Required PASS | Required PASS | Separate terminal |
| Final binary hash | Required PASS | Required PASS | Same source commit |

---

# 34. Definition of Done

Goal **DONE** hanya jika:

- [ ] Exact baseline evidence PASS.
- [ ] GOLD.i manifest/fingerprint PASS.
- [ ] GOLDm manifest/fingerprint PASS.
- [ ] Cross-profile isolation PASS.
- [ ] Current behavior corpus complete.
- [ ] Common pure strategy contract PASS.
- [ ] Bear incremental parity PASS untuk GOLD.i.
- [ ] Bear incremental parity PASS untuk GOLDm.
- [ ] Revised restart parity PASS untuk GOLD.i.
- [ ] Revised restart parity PASS untuk GOLDm.
- [ ] Event-driven reference runtime PASS.
- [ ] Signal-age guard PASS.
- [ ] Entry-drift guard PASS.
- [ ] Spread guard PASS.
- [ ] Invalidation-before-send PASS.
- [ ] Causal/tick-aware backtest PASS.
- [ ] GOLD.i live DEMO validation PASS.
- [ ] GOLDm REAL read-only market-data validation PASS dengan `orders_sent=0`.
- [ ] GOLDm isolated Strategy Tester execution validation PASS.
- [ ] MQL5 native scheduler PASS.
- [ ] Revised MQL5 parity 100% untuk kedua profile.
- [ ] Bear MQL5 parity 100% untuk kedua profile.
- [ ] Entry/SL/TP parity <= one profile tick.
- [ ] EA execution/management PASS.
- [ ] Python tidak mempunyai production order authority.
- [ ] Event outbox/DB/Telegram bridge PASS.
- [ ] GOLD.i happy-path E2E PASS.
- [ ] GOLDm happy-path engineering E2E PASS.
- [ ] Privacy/audience E2E PASS.
- [ ] Failure injection PASS.
- [ ] Restart/open-position recovery PASS.
- [ ] Dual-terminal independence PASS.
- [ ] Resource/storage/latency stability PASS.
- [ ] Fresh VM GOLD.i PASS.
- [ ] Fresh VM GOLDm PASS.
- [ ] `GoldEngine-GOLDi-vX.Y.Z.ex5` dihasilkan dan di-hash.
- [ ] `GoldEngine-GOLDm-vX.Y.Z.ex5` dihasilkan dan di-hash.
- [ ] Rollback binaries tersedia.
- [ ] Tidak ada P1 terbuka.
- [ ] Tidak ada required gate `BLOCKED`.
- [ ] REAL activation tetap disabled kecuali manusia mengotorisasi.

---

# 35. Kondisi yang Bukan Done

Jangan tutup goal bila hanya salah satu berikut tercapai:

```text
Python refactor selesai
Bear incremental selesai
unit tests hijau
backtest profit
MQL5 compile sukses
Strategy Tester berjalan
GOLD.i PASS tetapi GOLDm belum
GOLDm PASS tetapi GOLD.i belum
DEMO smoke sekali
Telegram terkirim
DB record tersedia
binary .ex5 ada
fresh VM belum diuji
fault injection belum diuji
resource trend belum diuji
required gate blocked
```

---

# 36. Required Agent Progress Report

Setiap update Codex harus memakai format:

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

Tidak boleh melaporkan “selesai” tanpa mengacu ke ledger G00–G21.

---

# 37. Required Final Report

Ketika semua gate lulus, final report harus memuat:

```text
Exact source SHA
Tree SHA
Parent SHA
Compiler version
Binary names
Binary SHA-256
Profile fingerprints
All gate statuses
All test commands
Python↔MQL5 parity summaries
GOLD.i E2E summary
GOLDm E2E summary
Cross-profile isolation summary
Failure/restart summary
Resource/storage/latency summary
Fresh-VM summary
Known limitations
Rollback procedure
REAL activation state
```

Jika satu required item tidak tersedia, final status bukan DONE.

---

# 38. Kalimat Pengarah Utama

> Backtest boleh melihat masa lalu; live engine hanya membawa bounded state yang diperlukan menuju sekarang.

> GOLD.i dan GOLDm berbagi core, tetapi tidak berbagi profile identity, account authority, risk, magic, state, audience, atau release binary.

> Begitu informasi strategi final tersedia, EA harus segera bereaksi atau menolak entry yang stale; jangan mengejar harga.

> Production decision, execution, dan position management berada di EA/MT5. Python hanya reference/research dan bridge non-critical.

> Satu profile PASS tidak pernah berarti dua profile PASS.

> Compile bukan E2E. Mock bukan E2E. BLOCKED bukan DONE.
