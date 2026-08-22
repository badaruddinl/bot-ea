# SOP Deploy E2E GOLD.i Portable dan Multi-Akun

## 1. Tujuan dan status

Dokumen ini adalah prosedur operasional end-to-end untuk menyiapkan,
memvalidasi, memasang, menjalankan, memperbarui, dan melakukan rollback engine
`GOLDI` pada satu atau beberapa akun MT5. Satu akun MT5 selalu menggunakan satu
terminal terisolasi.

Kontrak identitas, instrumen, leverage, dan sizing dijelaskan di
[`goldi-portable-account-instrument-sop.md`](goldi-portable-account-instrument-sop.md)
dan menjadi bagian wajib SOP ini.

Prosedur mengubah strategy, menguji, mengompilasi, dan membuat release `.ex5`
baru dijelaskan di
[`goldi-strategy-development-compile-release-sop.md`](goldi-strategy-development-compile-release-sop.md).

Status implementasi saat dokumen dibuat:

| Kemampuan | G21 saat ini | Target portable |
|---|---|---|
| GOLD.i# pada akun DEMO tersertifikasi | Tersedia | Dipertahankan |
| Nama simbol GOLD.i lain | Ditolak | Discovery dan binding eksplisit |
| Akun GOLD.i lain | Input login/server manual | Provisioning per deployment |
| Leverage selain binding awal | Belum menjadi binding tersendiri | Ditemukan dan disetujui |
| Beberapa akun GOLD.i | Belum didukung | Satu terminal per akun |
| Supervisor | Tepat GOLDI + GOLDM | Daftar instance GOLDI sebanyak N |
| Promosi DEMO ke REAL | Tidak otomatis | Binding baru, aktivasi manusia |

Binary G21 dan supervisor G20 sekarang masih profile-locked. Langkah bertanda
**TARGET PORTABLE** baru boleh dieksekusi setelah artefak pada bagian 18 dibuat,
diuji, dan dirilis. Dokumen ini tidak mengklaim fitur yang belum tersedia.

## 2. Prinsip arsitektur

### 2.1 Satu akun, satu terminal

Satu proses terminal MT5 hanya boleh memiliki satu identitas aktif. Untuk N
akun digunakan N instalasi/data directory MT5:

```text
GOLDI account A ─ terminal A ─ chart A ─ EA A ─ spool A ┐
GOLDI account B ─ terminal B ─ chart B ─ EA B ─ spool B ├─ bridge ─ DB/Telegram
GOLDI account C ─ terminal C ─ chart C ─ EA C ─ spool C ┘
```

Setiap baris wajib memiliki deployment ID, executable path, data directory,
login, server, simbol, leverage, magic/ownership, state, spool, dan log yang
terpisah. Yang boleh dibagi hanyalah binary read-only yang hash-nya sama,
strategy core, dan bridge yang mendukung routing multi-instance.

### 2.2 Tidak ada perpindahan diam-diam

Jika operator mengganti login, server, chart symbol, atau leverage di terminal
yang sedang berjalan, instance masuk `BINDING_INVALIDATED`. New order berhenti.
Instance tidak boleh mengadopsi identitas baru sampai discovery dan approval
ulang selesai.

### 2.3 Otoritas order

- Semua instalasi awal: `orders_enabled=false`.
- Discovery, compile, copy binary, startup, bridge, dan smoke test tidak boleh
  mengaktifkan order.
- DEMO order authority memerlukan tindakan manusia pada binding yang tepat.
- REAL memerlukan binding baru dan tindakan manusia terpisah.
- Kegagalan bridge/Telegram/DB tidak pernah mengaktifkan atau memperluas
  otoritas order.

## 3. Yang harus disediakan

Siapkan dan catat seluruh item berikut sebelum menyentuh terminal.

### 3.1 Akses dan keputusan manusia

- operator Windows yang berwenang memasang Scheduled Task;
- operator MT5 yang dapat login langsung pada setiap akun;
- pemilik keputusan untuk menerima hasil DEMO E2E;
- pemilik keputusan REAL jika kelak dipromosikan;
- daftar penerima Telegram GOLD.i yang disetujui;
- waktu maintenance ketika tidak ada posisi/watch yang akan dipindahkan;
- lokasi backup dan retensi evidence.

Password MT5, OTP, token Telegram, dan password Windows tidak boleh ditulis pada
worksheet, Git, log, screenshot, command line, atau chat.

### 3.2 Informasi setiap akun

Isi worksheet berikut untuk setiap deployment. Gunakan alias publik; login
lengkap hanya disimpan pada binding privat.

| Field | Contoh format | Wajib |
|---|---|---|
| Instance alias | `goldi-demo-a` | Ya |
| Exact login | bilangan positif | Ya, privat |
| Exact server | string dari MT5 | Ya |
| Trade mode | `DEMO` atau `REAL` | Ya |
| Exact chart symbol | misalnya `GOLD.i#` | Ya |
| Observed leverage | misalnya `1000` | Ya |
| Broker/terminal build | bilangan build | Ya |
| Terminal executable | absolute path unik | Ya |
| Terminal data path | absolute path unik | Ya |
| Audience | `goldi_approved` | Ya |
| Order authority awal | `DISABLED` | Harus |

### 3.3 Software

- Windows Server/Windows yang kompatibel dengan terminal broker;
- MetaTrader 5 dan MetaEditor dari broker;
- terminal build yang sudah direkam dan diuji;
- PowerShell 5.1 atau versi yang disertifikasi oleh release;
- Python 3.11 atau lebih baru hanya untuk bridge/evidence tooling;
- Git for Windows hanya jika host melakukan pull; deployment binary offline
  tidak memerlukan Git;
- release GOLD.i lengkap, checksum, source SHA, dan SOP rollback;
- akses internet hanya untuk broker dan Telegram bila notifikasi diaktifkan.

G21 dibangun pada Windows Server 2019 build 17763. Build terminal yang direkam
adalah GOLDI `6140`; SHA-256 binary tetap identitas release yang utama.

### 3.4 Kapasitas dan proteksi host

- ruang disk untuk N data directory MT5, state, spool, SQLite, log, dan backup;
- RAM/CPU dengan headroom saat N terminal aktif bersamaan;
- sinkronisasi waktu Windows aktif;
- zona waktu Windows dicatat, tetapi keputusan candle memakai server time;
- Windows Update tidak boleh melakukan reboot tak terencana saat market aktif;
- pengecualian antivirus hanya pada path yang benar-benar diperlukan, bukan
  seluruh drive;
- backup/snapshot VM sebelum instalasi atau update.

Jangan mengalikan angka resource satu terminal secara buta. Lakukan soak test N
terminal bersamaan dan sisakan minimal headroom operasional yang disetujui.

### 3.5 Secret dan Telegram

- token bot disimpan sebagai secret DPAPI atau secret store dengan ACL khusus;
- admin chat ID dan approved GOLD.i recipients disimpan di config privat;
- token tidak boleh berada di supervisor arguments;
- GOLD.i hanya mengirim final entry, execution outcome/close, dan health failure
  yang relevan;
- WATCH dan polling tick tidak dikirim ke Telegram.

## 4. Struktur direktori target

Contoh struktur untuk dua akun:

```text
C:\bot-ea\release\<version>\
  GoldEngine-GOLDi-v<version>.ex5
  SHA256SUMS
  source-commit.txt

C:\bot-ea\bindings\
  goldi-demo-a.json
  goldi-demo-b.json

C:\bot-ea\instances\goldi-demo-a\
  terminal\terminal64.exe
  data\
  state\
  spool\events.jsonl
  audit\
  health\health.json

C:\bot-ea\instances\goldi-demo-b\
  terminal\terminal64.exe
  data\
  state\
  spool\events.jsonl
  audit\
  health\health.json

C:\bot-ea\bridge\
  events.db
  health.json
```

Aturan path:

- jangan memakai satu data directory untuk dua terminal;
- jangan memakai satu state/spool file untuk dua deployment;
- jangan menaruh binding privat atau secret di checkout Git;
- jangan menghapus state/spool saat update; backup dahulu;
- path executable yang diawasi supervisor harus exact dan resolved.

## 5. Penamaan dan identitas multi-akun

Gunakan deployment ID stabil:

```text
goldi-<environment>-<account-alias>-<symbol-alias>-r<revision>
```

Contoh:

```text
goldi-demo-a-goldi-r1
goldi-demo-b-xauusd-r1
```

Deployment ID tidak berisi password atau login lengkap. Event wajib membawa:

- `deployment_id`;
- `profile_id=GOLDI`;
- strategy/profile version;
- setup/signal/order/position/event ID;
- exact symbol;
- account alias dan ID privat untuk admin audit;
- server time dan VM time;
- binding fingerprint;
- P/L, R:R, durasi, balance/equity snapshot pada close.

Kunci uniqueness order adalah gabungan server, login, symbol, magic, dan signal
ID. Provisioner harus menolak dua instance dengan ownership tuple yang sama.

Magic boleh sama pada akun yang benar-benar berbeda, tetapi registry tetap
wajib membuktikan tidak ada collision pada akun yang sama. Jika portable
release menyediakan magic per binding, nilainya harus disetujui dan tidak
dibuat acak pada setiap restart.

## 6. Persiapan release

### 6.1 Bekukan sumber

Catat:

- exact source commit;
- branch/tag;
- parent/tree SHA;
- strategy and profile fingerprint;
- MetaEditor dan terminal build;
- binary name dan SHA-256;
- hasil compile, parity, regression, DEMO E2E, restart, dan rollback.

Jangan deploy dari working tree kotor atau binary yang tidak ada dalam
`SHA256SUMS`.

### 6.2 Verifikasi release G21 yang ada

Perintah berikut hanya memverifikasi release profile-locked saat ini; perintah
ini tidak membuatnya portable:

```powershell
py -3.11 .\scripts\verify_g21_release.py `
  --repository-root . `
  --release-root .\release `
  --output .\runtime_data\release-verification.json
```

Hasil wajib `status=PASS` dan `violations=0`. Cocokkan hash binary secara
terpisah:

```powershell
Get-FileHash -Algorithm SHA256 `
  .\release\GoldEngine-GOLDi-v1.1.0.ex5
```

Untuk portable release baru, nama versi, hash, fingerprint, dan evidence harus
berasal dari release baru; jangan memakai hash G21 sebagai klaim sertifikasi.

## 7. Persiapan terminal per akun

Lakukan langkah ini satu per satu, bukan paralel.

1. Instal atau salin terminal broker ke directory instance yang unik.
2. Jalankan terminal secara interaktif satu kali.
3. Login melalui UI MT5; jangan menggunakan password pada command line.
4. Verifikasi login, server, DEMO/REAL, balance/equity, dan leverage.
5. Buka exact gold symbol yang akan digunakan.
6. Pastikan quote dan history M1/M5/M15/H1 tersedia.
7. Catat `TERMINAL_PATH`, `TERMINAL_DATA_PATH`, terminal build, dan symbol
   properties.
8. Tutup terminal secara normal.
9. Pastikan terminal lain tidak menggunakan executable/data path yang sama.

Untuk mode portable MT5, gunakan hanya jika broker build dan fresh-VM test
membuktikan `TERMINAL_DATA_PATH` benar-benar berada di directory instance.
Jangan menganggap parameter `/portable` berhasil tanpa membaca kembali path
dari MT5.

## 8. Discovery instrumen dan akun

### 8.1 TARGET PORTABLE: discovery read-only

Provisioner harus menjalankan EA/tool dalam mode discovery dengan order
authority nonaktif. Output minimal:

```text
DISCOVERY_COMPLETE
deployment candidate ID
login/server/mode/leverage
terminal executable/data path/build
symbol/currencies/digits/point/tick size
contract size/tick values
volume min/max/step
stops/freeze/filling/session
instrument fingerprint
orders_sent=0
order_api_calls=0
```

Operator membandingkan output dengan kontrak GOLD.i. Required baseline:

- contract size 100 troy ounces;
- minimum dan step volume maksimal `0.01`;
- tick size `0.01` USD;
- profit currency USD;
- tick economics konsisten;
- leverage sama dengan yang akan di-approve;
- `OrderCalcMargin` dan `OrderCheck` tersedia.

Mismatch berarti `INCOMPATIBLE`, bukan automatic conversion. GOLDm satu-ounce
tidak boleh lolos.

### 8.2 Binding approval

1. Review candidate JSON tanpa secret.
2. Isi exact login/server/mode/leverage/path secara privat.
3. Tetapkan deployment ID dan namespace unik.
4. Tetapkan audience dan ownership/magic.
5. Pastikan `orders_enabled=false`.
6. Canonicalize JSON dan hitung SHA-256 fingerprint.
7. Simpan binding dengan ACL hanya service/operator.
8. Simpan sanitized receipt dan checksum sebagai evidence.

Approval tidak boleh hanya berdasarkan nama simbol atau minimum lot.

## 9. Instalasi binary dan chart

Untuk setiap instance:

1. Verifikasi terminal berhenti dan tidak ada proses dengan executable path
   tersebut.
2. Backup binary, chart/profile, binding, state, dan spool lama.
3. Verifikasi SHA-256 binary release.
4. Salin binary ke `MQL5\Experts\bot-ea` pada data path instance.
5. Buka terminal interaktif.
6. Refresh Navigator dan attach EA ke exact chart.
7. Isi/imporkan binding fingerprint dan expected account fields.
8. Biarkan `EnableOrderAuthority=false`.
9. Simpan chart/profile startup.
10. Restart terminal dan pastikan EA terpasang kembali pada chart yang sama.

Receipt wajib setelah restart:

```text
ENGINE_STARTED
BINDING_MATCHED
PROFILE_VALIDATED
ENGINE_HEARTBEAT
ORDER_AUTHORITY_DISABLED
```

Jika salah satu tidak ada, jangan lanjut.

## 10. Bridge, database, dan Telegram

### 10.1 Multi-instance ingest

Bridge target harus menerima daftar spool, bukan hanya satu `--goldi-spool`.
Setiap event wajib memiliki `deployment_id`; SQLite menggunakan
`UNIQUE(event_id)` dan menyimpan deployment sebagai kolom wajib.

Satu bridge global boleh digunakan jika:

- ingest per spool independen dan fair;
- satu file rusak tidak menghentikan spool lain;
- checkpoint dan retry per deployment;
- Telegram routing tetap GOLD.i-approved;
- duplicate delivery ditekan;
- bridge failure tidak memengaruhi EA/order path.

Alternatifnya, gunakan satu bridge per instance dengan database terpisah. Ini
lebih mudah diisolasi tetapi memakai resource lebih banyak.

### 10.2 Format notifikasi

Entry final minimal:

```text
GOLD.i ENTRY READY / OPENED
Instance: <alias>
Instrumen: <exact symbol>
Signal ID: <id>
Order/position ID: <id jika sudah ada>
Side, volume, entry, SL, TP1, TP2
Waktu server: <ISO timestamp + offset>
Waktu VM: <ISO timestamp + timezone>
```

Close minimal:

```text
GOLD.i POSITION CLOSED
Instance/instrument/signal/order/position ID
Reason dan close price
P/L USD dan R
Planned dan realized R:R
Durasi posisi
Balance dan equity setelah close
Waktu server dan VM
```

Approved subscribers tidak perlu menerima login lengkap. Admin audit dapat
menerima account alias dan identifier yang dibutuhkan untuk debugging.

## 11. Startup tanpa login Windows

Ada dua mode yang harus diuji pada host tujuan.

### 11.1 Pilihan utama: task AtStartup

Supervisor berjalan sebagai Scheduled Task saat boot dan tidak menunggu login
operator. Task wajib:

- menggunakan service identity yang memiliki akses minimum ke instance paths;
- `Run whether user is logged on or not`;
- `At startup`, `StartWhenAvailable`, dan `MultipleInstances=IgnoreNew`;
- restart bounded setelah failure;
- tidak menyimpan password dalam script/config;
- hanya memulai executable paths yang sudah di-approve;
- menulis health atomik dan heartbeat bounded.

G20 memiliki installer AtStartup, tetapi supervisor saat ini memaksa tepat dua
profil dan belum dapat dipakai untuk N akun GOLD.i tanpa revisi.

### 11.2 Fallback: autologon lalu lock

Gunakan hanya jika MT5 broker terbukti tidak bekerja pada non-interactive
session. Gunakan Sysinternals Autologon/LSA, bukan plaintext
`DefaultPassword`, lalu Scheduled Task mengunci workstation. Risiko LSA harus
diterima eksplisit dan dibuktikan pada fresh-VM.

### 11.3 Uji wajib

1. Matikan seluruh terminal secara normal.
2. Reboot VM.
3. Jangan login melalui RDP/console.
4. Dari mekanisme out-of-band, tunggu health supervisor.
5. Verifikasi setiap process path, PID, account binding receipt, dan heartbeat.
6. Verifikasi bridge dan Telegram health.
7. Pastikan tidak ada duplicate terminal atau order.

Boot test tanpa login harus dilakukan lagi setelah menambah akun baru.

## 12. E2E satu akun DEMO

Jalankan berurutan dan simpan timestamp/evidence.

### E0 — static preflight

- release hash PASS;
- config/binding fingerprint PASS;
- terminal/data path unik;
- exact login/server/mode/leverage/symbol PASS;
- order authority disabled;
- tidak ada conflicting EA/task/magic.

### E1 — discovery no-order

- properties lengkap terbaca;
- compatible instrument PASS;
- `orders_sent=0`, `order_api_calls=0`;
- satu discovery event saja, tidak spam.

### E2 — startup/restart

- engine started/profile validated/heartbeat diterima;
- restart tidak mengulang closed bars;
- watch state pulih secara causal;
- tidak ada stale or duplicate order.

### E3 — observability failure

- putuskan bridge/DB/Telegram secara terkendali;
- EA tetap hidup dan tidak memperluas authority;
- spool bounded dan recoverable;
- setelah pulih, event dikirim at-least-once tanpa duplicate Telegram.

### E4 — DEMO order lifecycle

Setelah operator mengaktifkan DEMO pada binding exact:

1. tunggu `ENTRY_READY` asli dari closed-bar rules;
2. capture planned entry/SL/TP/volume dan time;
3. pre-send guards PASS;
4. broker submission dan retcode tercatat;
5. position ownership cocok;
6. management/partial/SL modification tercatat bila terjadi;
7. close outcome tercatat;
8. Telegram entry dan close terbaca manusia;
9. balance/equity/P&L/R/duration cocok dengan MT5 history.

Jangan memaksa sinyal atau mengubah strategi untuk mempercepat E2E. Strategy
Tester dapat menguji lifecycle deterministik, tetapi tidak menggantikan actual
DEMO E2E.

### E5 — mismatch matrix

Dengan order disabled, buktikan penolakan untuk:

- login salah;
- server salah;
- mode DEMO/REAL salah;
- leverage salah;
- symbol/suffix salah;
- contract size/tick value/volume step berubah;
- binary atau binding fingerprint salah;
- duplicate instance dan magic collision.

### E6 — rollback

- backup dibuat;
- previous binary/config dapat dipulihkan;
- state tidak tertukar;
- startup receipt sehat;
- authority tetap disabled setelah rollback.

Kelulusan satu akun membutuhkan E0–E6 PASS.

## 13. E2E opsional multi-akun

Multi-akun dijalankan hanya setelah masing-masing akun lulus E0–E6 sendiri.

### M0 — topology

- N executable dan data path unik;
- N deployment ID dan fingerprints unik;
- N state/spool/health path unik;
- ownership tuple tidak collision;
- satu registry deployment menjadi sumber kebenaran.

### M1 — concurrent startup

- start seluruh terminal melalui supervisor;
- tepat satu process per executable;
- semua heartbeat fresh;
- satu terminal gagal tidak direstart dengan path terminal lain;
- resource diukur bersamaan, bukan hasil per-instance yang dijumlahkan.

### M2 — cross-account isolation

- event A tidak memakai binding/state/order/position B;
- restart A tidak memengaruhi B;
- malformed spool A tidak menghentikan B;
- bridge routes account alias dengan benar;
- P/L dan balance snapshot berasal dari account yang tepat.

### M3 — simultaneous signals

- signal ID tetap unik lintas deployment;
- margin/exposure dihitung per account;
- satu broker reject tidak membatalkan order account lain;
- tidak ada global lock yang menukar ownership;
- Telegram menyebut instance sehingga event tidak rancu.

### M4 — VM restart

- reboot tanpa login;
- semua instance pulih;
- open position recovery tepat per account;
- tidak ada historical order resurrection;
- bridge checkpoint pulih per spool.

### M5 — remove/add account

- disable authority instance yang akan dihapus;
- selesaikan/serahkan posisi miliknya;
- stop exact terminal/task entry;
- archive, bukan delete, binding/state/spool;
- daftar instance lain tetap byte-for-byte sama;
- akun baru mengikuti E0–E6 dari awal.

Multi-akun baru PASS jika M0–M5 dan full single-account regression PASS.

## 14. Kriteria sebelum DEMO dianggap stabil

Tetapkan window dan threshold sebelum forward test; jangan mengubahnya setelah
melihat hasil. Minimal evidence operasional:

- jumlah trade selesai dan hari trading memenuhi kontrak forward;
- expectancy dan total R tercatat;
- drawdown dan margin usage tercatat;
- nol duplicate/foreign order;
- nol timestamp/lookahead mismatch;
- restart recovery PASS;
- tidak ada notification/storage growth tak terbatas;
- semua close cocok dengan MT5 history;
- tidak ada profile/account/symbol crossover.

Profit saja tidak cukup untuk menyatakan deployment stabil.

## 15. Promosi DEMO ke akun lain atau REAL

1. Bekukan hasil dan exact DEMO release/binding.
2. Jangan menyalin state/watch/open-position DEMO.
3. Siapkan terminal baru untuk akun tujuan.
4. Jalankan discovery dan binding approval dari awal.
5. Verifikasi trade mode serta leverage akun tujuan.
6. Jalankan E0–E3 dan E5–E6 dengan order disabled.
7. Jalankan broker preflight/read-only.
8. Catat keputusan manusia dan exact binding fingerprint.
9. Hanya operator berwenang yang boleh mengaktifkan order pada binding itu.
10. Monitor ketat event pertama dan siapkan immediate disable/rollback.

Pergantian leverage di portal broker menginvalidasi binding dan mengulang
langkah 3–10. Leverage lebih tinggi tidak menaikkan lot otomatis.

## 16. Update release

Untuk setiap instance, satu per satu:

1. disable new orders;
2. tentukan kebijakan posisi yang masih terbuka;
3. stop exact terminal;
4. backup binary/config/state/spool/chart;
5. verify new release SHA/fingerprint;
6. deploy binary secara atomik;
7. start dengan authority disabled;
8. require startup receipts dan recovery PASS;
9. smoke test bridge/Telegram;
10. aktifkan kembali hanya jika keputusan manusia mengizinkan.

Canary satu akun DEMO harus selesai sebelum rolling update akun lain. Jangan
update seluruh terminal sekaligus.

## 17. Monitoring, storage, dan incident response

### Health minimum

- supervisor PID dan start time;
- process/PID per terminal;
- engine/profile/binding status;
- last server tick dan last closed bar;
- last EA heartbeat;
- spool size/oldest undelivered event;
- bridge PID, DB state, Telegram last success;
- open position ownership;
- restart count dan last failure.

### Storage

- spool berisi transisi, bukan setiap tick/WATCH update;
- database menggunakan idempotent event ID;
- audit/log dirotasi berdasarkan batas ukuran dan retensi yang disetujui;
- health file ditulis atomik dan boleh diganti;
- state/binding tidak diperlakukan sebagai log;
- alarm sebelum disk penuh;
- backup menyimpan checksum dan dapat direstore.

### Severity

- P1: wrong account/symbol/magic, duplicate/foreign order, unintended REAL
  authority — disable affected authorities segera;
- P2: stale heartbeat, restart loop, state recovery mismatch — stop affected
  instance;
- P3: Telegram/bridge delay — trading tidak diperluas; perbaiki observability
  dan replay spool setelah pulih.

Jangan menutup posisi asing atau membunuh seluruh proses MT5 berdasarkan nama
process saja. Resolve dan cocokkan exact executable path serta ownership.

## 18. Artefak yang wajib diimplementasikan

SOP ini baru executable penuh setelah repository menyediakan dan menguji:

1. portable GOLD.i EA dengan `DeploymentBinding` terpisah dari strategy
   fingerprint;
2. discovery exporter yang read-only;
3. canonical binding generator dan verifier;
4. instrument fingerprint validator termasuk leverage/account binding;
5. installer satu instance yang idempotent;
6. supervisor berbasis array N instance, bukan tepat GOLDI + GOLDM;
7. instance registry dan duplicate ownership guard;
8. bridge multi-spool dengan `deployment_id`;
9. event/database schema multi-account dan migration rollback;
10. startup installer AtStartup serta optional autologon-lock fallback;
11. update/rollback script per exact instance;
12. compile, unit, parity, Strategy Tester, DEMO, restart, privacy, resource,
    multi-account, fresh-VM, dan release verifiers.

Nama command berikut adalah kontrak target dan **belum boleh dianggap tersedia**
sampai file serta test-nya benar-benar ada:

```powershell
.\scripts\discover-goldi-instance.ps1
.\scripts\approve-goldi-binding.ps1
.\scripts\install-goldi-instance.ps1
.\scripts\install-goldi-supervisor.ps1
.\scripts\test-goldi-e2e.ps1
.\scripts\rollback-goldi-instance.ps1
```

Setiap script harus memiliki `-WhatIf` atau `-ValidateOnly` bila relevan,
menolak secret di argument, memverifikasi resolved target path, dan gagal tanpa
perubahan parsial.

## 19. Checklist serah-terima

### Satu akun

- [ ] Exact release dan binary hash diverifikasi.
- [ ] Account/symbol/leverage discovery lengkap.
- [ ] Instrument economic contract kompatibel.
- [ ] Binding canonical dan fingerprint disetujui.
- [ ] Terminal/data/state/spool path unik.
- [ ] Initial authority disabled.
- [ ] E0–E6 PASS dengan evidence.
- [ ] Startup tanpa login PASS.
- [ ] Rollback dipraktikkan.

### Multi-akun

- [ ] Setiap akun lulus checklist satu akun.
- [ ] Registry dan ownership tuple unik.
- [ ] M0–M5 PASS.
- [ ] Concurrent soak/resource PASS.
- [ ] Bridge/Telegram menyebut instance yang tepat.
- [ ] Menambah/menghapus satu akun tidak memengaruhi lainnya.

### Aktivasi

- [ ] Operator menyetujui exact binding fingerprint.
- [ ] Order mode yang dipilih sesuai akun.
- [ ] Tidak ada authority lain pada ownership yang sama.
- [ ] Monitoring dan rollback siap.
- [ ] REAL, bila ada, diaktifkan manusia dan tercatat terpisah.

Tidak ada kotak yang boleh dicentang berdasarkan asumsi, mock, compile saja,
atau hasil akun lain.
