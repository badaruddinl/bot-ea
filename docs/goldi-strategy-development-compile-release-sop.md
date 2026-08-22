# SOP Pengembangan Strategy, Compile, dan Release GOLD.i

## 1. Tujuan dan batasan

Dokumen ini mengatur perubahan strategy `GOLDI` dari ide hingga binary `.ex5`
yang siap menjadi kandidat deployment. Alurnya mencakup research, editing
Revised BUY/Bear SELL, backtest dan OOS, Python/MQL5 parity, compile MetaEditor,
Strategy Tester, packaging, DEMO canary, rolling update multi-akun, dan
rollback.

Dokumen terkait:

- [Kontrak binding akun/instrumen](goldi-portable-account-instrument-sop.md)
- [SOP deploy E2E dan multi-akun](goldi-portable-e2e-deployment-sop.md)

Scope utama adalah `GOLDI`. `GOLDM` bukan target tuning. Karena beberapa source
MQL5/Python masih shared, GOLDM tetap wajib melalui compile dan non-regression
agar perubahan GOLD.i tidak menyeberang profil.

REAL order authority harus nonaktif selama seluruh proses. Compile, backtest,
Strategy Tester, DEMO E2E, atau profit historis tidak pernah mengaktifkan REAL.

## 2. Klasifikasi perubahan

Klasifikasikan sebelum membuat branch.

| Kelas | Contoh | Strategy test | Compile `.ex5` | Deployment binding baru |
|---|---|---:|---:|---:|
| Dokumentasi | SOP/penjelasan | Tidak | Tidak | Tidak |
| Binding akun | login/server/leverage/path | Tidak, kecuali sizing economics berubah | Tidak | Ya |
| Instrumen setara | suffix simbol, spec tetap | Regression guard | Hanya jika binary belum portable | Ya |
| Parameter strategy | RSI, ATR, RR, timeout | Ya | Ya | Ya, fingerprint berubah |
| Logic strategy | Revised/Bear/state machine | Ya penuh | Ya | Ya |
| Execution/management | guards, partial, trailing | Ya penuh + lifecycle | Ya | Ya |
| Shared core | type/scheduler/outbox | Ya dua profil | Ya dua profil | Sesuai fingerprint |

Satu batch hanya mengandung satu semantic concern. Jangan mencampur tuning,
refactor, portability, Telegram, deployment, dan aktivasi akun dalam commit
yang sama.

## 3. Source of truth

Komponen GOLD.i yang harus dibaca sebelum perubahan:

```text
config/engine_profiles/GOLDI.json
config/final/goldi/revised.json
config/final/goldi/bear.json
config/final/goldi/portfolio.json
src/gold_engine_core/
mt5/Include/bot-ea/GoldEngineRevised*.mqh
mt5/Include/bot-ea/GoldEngineBear*.mqh
mt5/Include/bot-ea/GoldEngineExecution*.mqh
mt5/Experts/bot-ea/GoldEngine-GOLDi.mq5
tests/gold_engine_core/
tests/mql5/
```

Python reference dan MQL5 live implementation harus memakai aturan yang sama.
Replay dan incremental feeder juga harus memanggil rule implementation yang
sama. Jangan mempertahankan cabang replay khusus yang tidak digunakan live.

Revised BUY dan Bear SELL merupakan dua strategy state machine yang berbeda,
meskipun hasilnya masuk satu portfolio/balance. Jika hanya Revised yang diubah,
hash dan behavior Bear dibekukan; demikian pula sebaliknya.

## 4. Persiapan yang wajib disediakan

### 4.1 Repository dan toolchain

- exact remote branch dan baseline SHA;
- clean worktree khusus;
- Git, Python sesuai `pyproject.toml`, dependencies `.[live,dev]`;
- Ruff, mypy, pytest, pytest-cov;
- MetaTrader 5 dan MetaEditor yang build-nya dicatat;
- dedicated Strategy Tester profile;
- terminal DEMO GOLD.i terisolasi;
- external evidence directory di luar checkout;
- ruang untuk tick/bar datasets dan raw tester reports.

### 4.2 Data

- causal M1, M5, M15, dan H1 bars dari exact server/symbol;
- tick data jika menguji execution/SL/TP/intrabar order;
- timezone/offset broker dan DST metadata;
- symbol specification snapshot per dataset;
- spread, contract size, tick value, volume limits, dan leverage context;
- immutable dataset checksum dan last closed bar timestamp;
- train/development/OOS split yang ditetapkan sebelum tuning.

Dataset yang timestamp, source, symbol, atau checksum-nya tidak jelas tidak
boleh digunakan untuk PASS.

### 4.3 Evidence manifest

Sebelum editing, buat ledger yang mencatat:

- objective dan affected scope;
- exact baseline SHA/tree/parent/ref;
- strategy/profile/config/blob hashes;
- dataset hashes dan date ranges;
- tool versions dan commands;
- baseline metrics per window;
- acceptance threshold yang dibekukan;
- order authority `DISABLED`.

## 5. Branch dan baseline

1. Fetch remote dan resolve exact target SHA.
2. Pastikan status bersih; research data tidak masuk worktree release.
3. Buat branch `feature/goldi-strategy-<single-concern>`.
4. Rekam hashes source/config GOLDI dan GOLDM sebelum perubahan.
5. Jalankan baseline focused tests dan backtest yang akan dibandingkan.
6. Simpan raw evidence di external evidence root; Git hanya menyimpan manifest,
   checksum, dan ringkasan.

Tidak boleh rebase/force-push/amend setelah evidence release mulai direkam.

## 6. Menulis proposal strategy

Proposal harus menjawab:

- masalah yang dibuktikan oleh trade/event mana;
- strategy yang berubah: Revised BUY, Bear SELL, atau management;
- penyebab yang dihipotesiskan;
- data yang dipakai untuk mengembangkan ide;
- data yang dilarang untuk tuning karena menjadi OOS;
- parameter/logic yang berubah dan yang dibekukan;
- expected benefit dan known trade-off;
- kondisi yang membuat eksperimen gagal;
- rollback reference.

Jangan mengubah aturan hanya agar lima evidence tertentu tampak benar. Lima
evidence boleh menjadi regression corpus, tetapi expectancy, drawdown,
causality, dan OOS tetap menentukan kelayakan.

## 7. Aturan editing strategy

### 7.1 Pure deterministic rules

- logic tidak membaca MT5, DB, Telegram, env, clock OS, atau sleep;
- semua time berasal dari event/bar/tick input;
- hanya candle closed yang boleh membuat keputusan confirmation;
- forming/future bar harus ditolak;
- state transition dan reason code eksplisit;
- hot path incremental dan bounded;
- restart state versioned dan deterministic;
- identity setup/signal stabil dan idempotent.

### 7.2 Revised BUY

Perubahan Revised harus menjaga state lifecycle dan causal evidence. Parameter
room, range/retest, momentum, exhaustion, Fibonacci, RSI/Stochastic, target,
partial close, atau stop management tidak boleh dipukul rata untuk semua
setup. Setiap perubahan harus memiliki unit tests yang menunjukkan kondisi
aktif dan kondisi saat aturan tidak boleh aktif.

### 7.3 Bear SELL

Bear wajib tetap incremental dan stateful setelah warm-up bounded. Jangan
mengembalikan live path ke replay 30 hari. H1 context, M5 setup/retest, dan M1
confirmation harus diproses sekali per closed bar. Warm-up tidak boleh
tradable dan tidak boleh menghidupkan order historis.

### 7.4 Execution dan position management

Signal plan membekukan entry, SL, TP, volume, invalidation, dan deadline.
Immediately-before-send guards tetap memeriksa age, drift, spread,
invalidation, duplicate, position/exposure, margin, account, symbol, mode,
magic, dan broker constraints. Structural SL/TP tidak boleh digeser untuk
mengejar current quote.

Partial/TP1/TP2/trailing changes memerlukan tick-aware lifecycle tests. Outcome
harus merekonsiliasi realized P/L, R, duration, balance/equity, dan broker
history.

### 7.5 GOLDM isolation

Untuk perubahan GOLD.i:

- jangan mengubah `config/final/goldm/*`;
- jangan mengubah GOLDM sizing, symbol, audience, magic, atau authority;
- shared source change harus memiliki alasan dan dual-profile tests;
- GOLDM behavior corpus harus sama;
- jika shared source membuat binary GOLDM berubah, release notes harus
  menjelaskan byte/hash change dan membuktikan semantic parity;
- jika tidak ada alasan untuk merilis GOLDM, pertahankan certified GOLDM
  artifact dan checksum.

## 8. Versioning dan fingerprint

Gunakan semantic versioning:

- patch: semantic bug fix tanpa intended signal change;
- minor: parameter/behavior strategy baru yang backward-incompatible terhadap
  event outcomes;
- major: contract/state/event schema atau arsitektur besar.

Perubahan wajib sinkron pada:

- MQL5 `#property version`;
- GOLDI profile version;
- strategy version;
- Revised/Bear config hashes;
- profile/strategy fingerprint;
- event payload version jika schema berubah;
- state migration version;
- release binary filename dan manifest.

Jangan mengedit hash secara manual berdasarkan perkiraan. Gunakan canonical
serialization/generator yang diuji dan simpan input serta output hash.

## 9. Urutan research dan backtest

Urutan yang dikunci untuk eksperimen strategy berikutnya:

1. jalankan tiga partial windows;
2. jika belum memadai, diagnosis/tweak hanya dengan corpus 4–19 Agustus 2026;
3. ulangi tiga partial windows setelah kandidat dibekukan;
4. jika ketiganya baik, jalankan full suite;
5. setelah full suite lulus, lakukan OOS/forward validation yang belum pernah
   digunakan untuk tuning.

Definisi window:

| Nama | Rentang |
|---|---|
| Partial A | 1 Januari 2025 sampai last certified closed bar tahun 2026 |
| Partial B | 1 November 2025 sampai 15 Februari 2026 |
| Partial C | 1 Juni 2026 sampai last certified closed bar |
| Diagnostic evidence | 4–19 Agustus 2026 |
| Full suite | 1 Januari 2020 sampai last certified closed bar |

Partial A memang mencakup partial B/C; ketiganya tetap dilaporkan terpisah agar
perubahan regime terlihat. Setiap run memulai balance sesuai skenario yang
dibekukan, bukan melanjutkan balance dari window lain. Portfolio combined test
menjalankan Revised dan Bear pada satu shared balance dalam satu chronological
event stream.

Periode 2020–2023 dapat dianotasi sebagai konteks COVID-19. Periode event lain,
termasuk konflik geopolitik, harus memakai tanggal dan sumber eksternal yang
terverifikasi. Annotation hanya untuk analisis regime; strategy tidak boleh
membaca label masa depan tersebut.

### 9.1 Baseline dan kandidat

Pada setiap window bandingkan minimal:

- exact baseline release;
- candidate change saja;
- portfolio Revised + Bear;
- fixed balance/lot scenario yang disetujui;
- balance-tier scenario bila scope sizing ikut diuji.

### 9.2 Metrics wajib

- entry count dan outcome count;
- gross/net P/L;
- total R dan expectancy R;
- win/loss/breakeven;
- profit factor;
- maximum closed dan intratrade drawdown;
- margin usage dan stop-out;
- MFE/MAE;
- holding duration dan session/hour distribution;
- TP1/TP2/SL/management reason distribution;
- duplicate, stale, rejected, and invalidated signals;
- result per Revised, Bear, dan combined balance.

Jangan menyebut total P/L sebagai profit bila balance mengalami stop-out atau
run tidak menyelesaikan seluruh window.

### 9.3 Causality dan OOS

- forming/future bars tidak boleh masuk keputusan;
- spread/tick execution memakai data yang tersedia pada timestamp tersebut;
- train/development dan OOS hashes disimpan terpisah;
- setelah candidate config dibekukan, jangan tuning dari OOS result;
- failure pada OOS menghasilkan FAIL atau eksperimen baru dengan OOS baru,
  bukan mengubah threshold secara retrospektif.

## 10. Test pipeline sebelum compile

Instal dependencies pada environment bersih:

```powershell
python -m pip install -e ".[live,dev]"
```

Jalankan focused tests untuk source yang berubah, lalu named gates:

```powershell
python scripts\validate_goal_gate.py validate-profile-contracts
python scripts\validate_goal_gate.py validate-causality
python scripts\validate_goal_gate.py validate-replay
python scripts\validate_goal_gate.py validate-incremental
python scripts\validate_goal_gate.py validate-execution-guards
python scripts\validate_goal_gate.py validate-python-parity
python scripts\validate_goal_gate.py validate-mql5-parity-goldi
python scripts\validate_goal_gate.py validate-mql5-parity-goldm
python scripts\validate_goal_gate.py validate-cross-profile
python scripts\validate_goal_gate.py validate-event-contract
python scripts\validate_goal_gate.py validate-unit
```

Quality checks untuk changed Python packages:

```powershell
python -m ruff format --check src tests scripts
python -m ruff check src tests scripts
python -m mypy <changed-packages>
python -m pytest --cov=<safety-critical-package> --cov-report=term-missing
```

Jangan memakai placeholder `<changed-packages>` secara literal; isi daftar
package yang benar pada ledger. Threshold coverage mengikuti release contract
dan tidak boleh diturunkan agar gate lulus.

Required mutation failures meliputi symbol, account, server, mode, leverage,
magic, audience, config hash, future/forming bar, replay in live path,
age/drift/invalidation guard, dan duplicate ownership.

## 11. Python/MQL5 parity

Sebelum compile release:

1. buat deterministic vectors dari Python reference;
2. replay Python incremental pada vectors yang sama;
3. jalankan MQL5 Revised/Bear harness;
4. jalankan Strategy Tester pada equivalent data;
5. bandingkan event order, state, side, reason, setup/signal ID, dan geometry.

Acceptance:

- event/state/reason parity `100%`;
- entry/SL/TP tolerance maksimal satu tick profile;
- no future/forming bar;
- no duplicate event/order;
- restart parity di seluruh watch/entry/open/close points;
- GOLDM corpus tidak berubah untuk GOLDI-only semantic change.

Equity curve yang mirip bukan parity.

## 12. Compile MetaEditor

### 12.1 Preflight

- working tree dan source commit exact;
- MetaEditor path/build tercatat;
- no untracked generated source in compile tree;
- include files berasal dari checkout yang sama;
- evidence directory baru dan kosong dari hasil run sebelumnya;
- order authority default tetap disabled.

### 12.2 Compile kedua profil

Repository menyediakan build gate berikut:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\validate-g21-mql5-build.ps1 `
  -MetaEditorPath "C:\Program Files\MetaTrader 5\MetaEditor64.exe" `
  -EvidenceRoot ".ci-evidence\mql5-build-<version>"
```

Script mengompilasi:

```text
mt5\Experts\bot-ea\GoldEngine-GOLDi.mq5
mt5\Experts\bot-ea\GoldEngine-GOLDm.mq5
```

Atau jalankan named gate:

```powershell
$env:METAEDITOR_PATH = "C:\Program Files\MetaTrader 5\MetaEditor64.exe"
python scripts\validate_goal_gate.py validate-mql5-build
```

PASS hanya jika kedua compile log memuat `Result: 0 errors, 0 warnings`.
MetaEditor exit code saja tidak cukup.

### 12.3 Capture output

Untuk setiap `.ex5` catat:

- resolved source and output path;
- source commit and tree SHA;
- MetaEditor and terminal build;
- compile command, exit code, and log SHA;
- binary size, UTC modified time, and SHA-256;
- profile/strategy/config/binding compatibility fingerprints.

Jangan menyalin `.ex5` dari directory lain hanya karena namanya sama.

## 13. Strategy Tester

Gunakan dedicated tester terminal/profile, bukan terminal akun operator.

Konfigurasi wajib direkam:

- exact EA binary hash;
- symbol and symbol spec snapshot;
- timeframe and date range;
- `Every tick based on real ticks` untuk execution-sensitive tests;
- deposit, currency, leverage, commission, and spread model;
- inputs/set file hash;
- terminal/tester build;
- modelling quality/data availability;
- report/log paths and checksums.

Run matrix minimal:

- Revised only;
- Bear only;
- combined portfolio on one balance;
- each partial window;
- diagnostic evidence regression;
- full suite;
- frozen OOS;
- restart/open-position lifecycle harness;
- intended compatible GOLD.i instrument specs;
- leverage/margin variants that are actually approved.

Tester must reconcile order/deal/position IDs, P/L, R, duration, and balance
against engine events. Mock and compile are not Strategy Tester E2E.

## 14. Release candidate packaging

Release tree minimal:

```text
release\goldi\<version>\
  GoldEngine-GOLDi-v<version>.ex5
  SHA256SUMS
  source-commit.txt
  build-environment.md
  profile-manifest.json
  strategy-manifest.json
  config-hashes.json
  parity.md
  backtest-partials.md
  backtest-full-suite.md
  oos.md
  strategy-tester.md
  demo-e2e.md
  cross-profile.md
  restart-failure.md
  resource.md
  known-limitations.md
  rollback.md
  rollback\<previous-certified-binary>
```

`SHA256SUMS` mencakup seluruh shipped artifacts. Raw tick data, tester logs, dan
large reports tetap di external evidence root dengan checksum/link dari Git.

Release verifier harus diperbarui untuk versioned portable tree; current
`verify_g21_release.py` hanya authoritative untuk layout G21 sekarang.

## 15. Candidate acceptance

Release candidate hanya boleh maju jika:

- seluruh focused/named/full regression PASS;
- partial → diagnostic → partial → full suite order dipatuhi;
- frozen OOS PASS sesuai threshold yang ditetapkan sebelumnya;
- Python/MQL5/Tester parity PASS;
- compile dua profil `0 errors, 0 warnings`;
- GOLDM non-regression PASS;
- no lookahead/timestamp/duplicate/restart mismatch;
- no unintended authority or profile crossover;
- release tree and checksums verified;
- rollback binary/procedure tersedia;
- REAL orders tetap disabled.

Jika satu required gate gagal, status release `FAIL` atau `BLOCKED`, bukan PASS
dengan catatan kecil.

## 16. DEMO canary dan multi-akun rollout

1. Deploy candidate ke satu dedicated GOLD.i DEMO canary.
2. Mulai dengan order disabled; jalankan E0–E3 dan E5–E6 dari deployment SOP.
3. Operator mengaktifkan DEMO binding canary.
4. Selesaikan actual DEMO E4 dan forward window yang dibekukan.
5. Bandingkan candidate dengan baseline pada window/timestamp yang sama.
6. Jika PASS, rolling deploy satu akun DEMO berikutnya pada satu waktu.
7. Setelah setiap instance, verifikasi heartbeat, ownership, state recovery,
   Telegram, dan no crossover sebelum melanjutkan.
8. Jalankan multi-account M0–M5 setelah semua single-instance tests lulus.

Jangan melakukan big-bang update seluruh akun. Akun REAL, bila kelak ada,
mengikuti promotion workflow terpisah dan human activation.

## 17. Mengubah strategy setelah release

EA yang sedang berjalan tidak boleh menerima hot edit strategy/config.
Perubahan menghasilkan versioned release baru.

Saat update:

- hentikan new entries;
- tetapkan apakah open position tetap dikelola binary lama sampai close atau
  dimigrasikan melalui kontrak yang diuji;
- jangan mengubah management policy posisi terbuka secara diam-diam;
- backup binding/state/spool/binary;
- deploy canary dengan authority disabled;
- rollback bila startup/recovery/hash mismatch.

## 18. Rollback pengembangan dan release

Rollback target adalah exact previous certified release, bukan source terbaru
yang kebetulan compile.

1. Disable candidate authority.
2. Stop exact candidate terminal/instance.
3. Preserve candidate logs, state, spool, binding, and hashes.
4. Restore previous binary/config/profile fingerprints.
5. Validate account/symbol/leverage/magic/ownership.
6. Start with authority disabled.
7. Require startup/recovery/bridge receipts.
8. Reactivate only through the previous approved binding decision.

GOLDM tidak boleh disentuh oleh rollback GOLD.i.

## 19. Required evidence checklist

- [ ] Exact baseline SHA/tree/parent/ref and clean status.
- [ ] Change proposal, scope, risks, and frozen thresholds.
- [ ] Dataset/timezone/symbol specification checksums.
- [ ] Baseline and candidate partial results.
- [ ] Diagnostic 4–19 August regression.
- [ ] Repeated partial results after freeze.
- [ ] Full-suite results.
- [ ] Frozen OOS results.
- [ ] Focused/unit/causal/incremental/restart/execution tests.
- [ ] Python/MQL5/Strategy Tester parity.
- [ ] GOLDM non-regression.
- [ ] Ruff/mypy/coverage results.
- [ ] Dual-profile compile logs with zero errors/warnings.
- [ ] Binary hashes and release manifest.
- [ ] DEMO canary E2E and forward evidence.
- [ ] Multi-account isolation if enabled.
- [ ] Fresh-VM startup and rollback.
- [ ] Known limitations.
- [ ] REAL orders remained disabled throughout engineering.

## 20. Definition of done

Strategy work selesai hanya jika source, tests, evidence, `.ex5`, manifests,
checksums, DEMO E2E, rollback, dan documentation berasal dari exact commit yang
sama. Merge, deploy, dan REAL activation adalah keputusan terpisah. Tidak ada
hasil backtest, compile, atau DEMO profit yang menggabungkan ketiga keputusan
tersebut secara otomatis.
