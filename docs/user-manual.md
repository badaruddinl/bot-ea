# User Manual

## Dokumen Ini Untuk Siapa

Dokumen ini ditujukan untuk operator non-teknis yang memakai aplikasi desktop Qt `bot-ea`.

Tujuannya:

- tahu cara membuka aplikasi
- tahu urutan tombol yang benar
- tahu arti halaman dan status utama
- tahu kapan aman lanjut
- tahu kapan harus berhenti

Dokumen ini hanya menjelaskan perilaku yang sudah ada di aplikasi sekarang. Aplikasi sekarang sudah punya startup gate first-pass sebelum workspace utama terbuka, tetapi ide master brief lain seperti mode dev/operator terpisah penuh dan halaman review akun masih belum ada.

## Fungsi Aplikasi Saat Ini

Aplikasi desktop membantu Anda untuk:

- memeriksa koneksi MT5
- memeriksa apakah `codex-cli` siap dipakai
- melihat preview market, lot, dan risiko
- menjalankan runtime polling secara supervised
- mengaktifkan live mode secara eksplisit
- menyetujui atau menolak proposal live
- membaca telemetry dan validation summary setelah runtime berjalan

Batas penting:

- aplikasi ini belum siap untuk live trading tanpa pengawasan
- mode paling aman tetap `dry-run` atau demo

## Cara Menjalankan Aplikasi

Jalankan Qt app sebagai entrypoint utama:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Dalam penggunaan normal:

- Anda tidak perlu membuka websocket service manual di jendela lain
- GUI akan mencoba mengelola service lokal sendiri
- sebelum halaman utama terbuka penuh, aplikasi akan melewati startup gate

Script `run-websocket-service.ps1` masih ada, tetapi itu sekarang lebih cocok untuk debugging atau pengujian backend terpisah.

## Sebelum Mulai

Lakukan ini dulu:

1. Buka `MetaTrader 5`.
2. Login ke akun yang benar.
3. Pastikan simbol yang ingin dipakai tersedia di broker, misalnya `EURUSD` atau `XAUUSD`.
4. Pastikan `codex --version` berhasil di terminal Windows.
5. Baru jalankan GUI Qt.

Checklist cepat:

- MT5 terbuka
- akun sudah login
- `codex-cli` terpasang
- mulai dari akun demo
- mulai dari `dry-run`

## Startup Gate First-Pass

Saat aplikasi dibuka sekarang, workspace utama tidak langsung terbuka.

Urutan pemeriksaan awal:

1. service lokal
2. MT5
3. Codex

Kalau ketiganya lolos:

- workspace utama akan terbuka

Kalau salah satunya gagal:

- Anda akan tetap berada di layar startup gate
- perbaiki dependency yang gagal dulu

Yang belum termasuk di startup gate saat ini:

- review akun berubah
- reconnect overlay
- validasi AI workspace/documents/context seperti di master brief

## Kenali Halaman Aplikasi

Qt app sekarang memakai sidebar dengan 5 halaman.

### 1. `Dashboard`

Fungsi:

- melihat ringkasan status operator
- melihat readiness chips
- melihat market snapshot, manual order envelope, dan risk envelope
- melihat overview run, lot, spread, dan mode runtime

Ini adalah halaman ringkas, bukan tempat utama untuk mengubah semua parameter.

### 2. `Strategy`

Fungsi:

- mengatur parameter trading
- mengatur parameter Codex
- menjalankan tombol aksi utama

Di halaman ini ada kelompok utama:

- `Trade Setup`
- `Codex`
- `Actions`

### 3. `History`

Fungsi:

- memuat telemetry runtime
- membaca validation summary
- meninjau hasil run sebelumnya

Gunakan halaman ini sesudah runtime berjalan.

### 4. `Logs`

Fungsi:

- membaca runtime feed
- membaca event dan error
- melihat endpoint dan tick terbaru yang sudah masuk ke UI

### 5. `Settings`

Fungsi:

- melihat endpoint websocket
- melihat model default
- melihat poll interval
- melihat ringkasan runtime DB

Catatan:

- halaman ini bukan settings produk yang lengkap seperti di master brief
- belum ada pengelolaan AI workspace, documents folder, atau account-scoped context di sini

## Arti Area Penting di Halaman `Strategy`

### `Trade Setup`

Bidang utama:

- `Symbol (from MT5)`
- `Timeframe`
- `Strategy Style`
- `Stop Loss Distance (points, min X)`
- `Capital Mode`
- `Capital To Use (USD)`
- `Lot Mode`
- `Manual Lot Request`
- `Manual Side Only`
- `Log File (Runtime DB)`

Arti sederhananya:

- `Symbol`: instrumen broker yang dipilih
- `Timeframe`: kerangka waktu analisis
- `Strategy Style`: gaya strategi aktif
- `Stop Loss Distance`: jarak stop loss untuk preview risiko
- `Capital Mode`: cara modal dibaca oleh risk engine
- `Capital To Use`: basis modal yang diizinkan
- `Lot Mode`: apakah lot dihitung otomatis atau memakai request manual
- `Manual Lot Request`: lot manual jika mode manual dipakai
- `Manual Side Only`: arah order untuk aksi manual
- `Log File (Runtime DB)`: file SQLite untuk runtime dan telemetry

### `Codex`

Bidang utama:

- `Codex Command`
- `AI Model`
- `Codex Work Folder`
- `Check Market Every (s)`

Arti sederhananya:

- `Codex Command`: command executable, biasanya `codex`
- `AI Model`: model yang dipakai runtime
- `Codex Work Folder`: folder kerja project untuk Codex
- `Check Market Every (s)`: jarak polling market oleh runtime

## Tombol Utama dan Fungsinya

Label tombol di Qt app sekarang masih berbahasa Inggris/operator.

### `Check MT5`

Fungsi:

- memeriksa apakah terminal MT5 bisa dibaca
- memeriksa akun, tick, dan simbol dasar

### `Load Codex`

Fungsi:

- memeriksa apakah `codex-cli` bisa dipanggil
- membaca versi CLI dan model yang dipilih

### `Preview`

Fungsi:

- mengambil preview manual terbaru dari broker snapshot
- memperbarui market snapshot, manual order envelope, dan risk envelope

### `Preflight`

Fungsi:

- meminta broker/risk layer memeriksa apakah setup order lolos pemeriksaan sebelum submit

### `Execute Manual`

Fungsi:

- mencoba menjalankan order manual dari setup saat ini

Catatan:

- kalau live belum aktif, hasilnya bisa `DRY_RUN_OK`
- kalau broker menolak parameter, hasilnya bisa `REJECTED`

### `Play Runtime`

Fungsi:

- memulai polling runtime di backend

Ini tidak sama dengan langsung membuka posisi.

### `Stop Runtime`

Fungsi:

- menghentikan runtime aktif

### `Enable Live` / `Disable Live`

Fungsi:

- mengubah runtime dari dry-run menjadi live-gated

Ini tetap bukan izin trading otomatis tanpa review.

### `Approve`

Fungsi:

- menyetujui proposal order live yang sedang pending

### `Reject`

Fungsi:

- menolak proposal order live yang sedang pending

### `Telemetry`

Fungsi:

- memuat ulang telemetry run, validation summary, dan review status

## Urutan Pakai yang Disarankan

Ikuti urutan ini:

1. Buka MT5 dan login.
2. Jalankan Qt app.
3. Biarkan startup gate memeriksa service, MT5, lalu Codex.
4. Setelah workspace terbuka, buka halaman `Strategy`.
5. Atur `Symbol`, `Timeframe`, `Strategy Style`, dan modal.
6. Klik `Preview`.
7. Klik `Preflight`.
8. Jika hasil aman, klik `Play Runtime`.
9. Biarkan runtime berjalan beberapa cycle.
10. Buka `History` atau klik `Telemetry`.
11. Tetap di dry-run dulu.
12. Hanya jika benar-benar perlu, gunakan `Enable Live`.
13. Jika ada proposal live, pilih `Approve` atau `Reject`.

## Aturan Penting Saat Runtime Aktif

Saat runtime sudah berjalan:

- beberapa aksi manual MT5 akan dibatasi
- ini sengaja dilakukan agar jalur manual tidak merusak koneksi IPC MT5 yang sedang dipakai runtime

Artinya:

- jika ingin banyak mengubah setup manual, lebih aman `Stop Runtime` dulu
- sesudah itu baru `Preview`, `Preflight`, atau `Execute Manual`

## Arti Status Kesiapan

Di bagian readiness, perhatikan:

- `Service`
- `MT5`
- `Codex`
- `Runtime`
- `Run ID`
- `Approval`

Interpretasi umum:

- `Service connected`
  - GUI sudah terhubung ke websocket backend
- `MT5 ready`
  - probe MT5 berhasil
- `codex-cli ...`
  - probe Codex berhasil
- `Runtime stopped`
  - runtime tidak sedang berjalan
- `NO_TRADE: ...`
  - runtime masih hidup, tetapi cycle terakhir memutuskan tidak entry
- `Approved ...`
  - proposal live terakhir disetujui

`NO_TRADE` bukan berarti runtime pasti berhenti.

## Cara Membaca Snapshot Cards

### `Market Snapshot`

Menampilkan:

- symbol
- bid
- ask
- spread
- equity
- free margin
- execution mode

Saat runtime aktif, data market terbaru idealnya datang dari event runtime, bukan dari tombol manual.

### `Manual Order Envelope`

Menampilkan:

- `lot_mode`
- `requested_lot`
- `final_lot`
- `broker_min_lot`
- `broker_max_lot`
- `margin_for_min_lot_usd`
- `margin_for_final_lot_usd`
- `manual_order_result`
- `why_blocked`

Ini menjawab:

- lot final yang akan dipakai berapa
- apakah lot di-resize
- apakah broker/modal masih mengizinkan order manual

### `Risk Envelope`

Menampilkan:

- lot hasil risk sizing
- risk budget
- estimated loss
- warning atau blocker

Catatan:

- kartu ini lebih dekat ke sudut pandang risk engine
- jangan campurkan otomatis dengan `Manual Order Envelope`

## Cara Membaca Telemetry

Saat membuka `History` atau menekan `Telemetry`, fokus ke:

- `status`
- `last_action`
- `reject_rate`
- `recent_execution_events`
- `recent_rejections`
- `validation_summary`

Kalau yang terlihat:

- `DRY_RUN_OK`
  - order hanya diuji, belum dikirim live
- `PRECHECK_OK`
  - broker/risk precheck lolos
- `REJECTED`
  - ada penolakan dari broker atau guard internal
- `NO_TRADE`
  - runtime memilih tidak membuka posisi pada cycle itu

## Error Umum

### 1. `NO IPC connection`

Artinya:

- Python kehilangan koneksi ke MT5

Yang harus dilakukan:

1. pastikan hanya satu MT5 yang dipakai
2. jangan spam aksi manual saat runtime aktif
3. cek apakah terminal MT5 masih terbuka dan login
4. `Check MT5` lagi

### 2. `codex exec timed out after 60 seconds`

Artinya:

- `codex-cli` terlalu lama menjawab

Yang harus dilakukan:

1. ulang `Load Codex`
2. cek model yang dipakai
3. cek folder kerja dan beban prompt

### 3. `codex contract invalid`

Artinya:

- respons Codex tidak mengikuti kontrak output yang diminta runtime

Sekarang runtime akan menandai ini dengan lebih jelas daripada sebelumnya.

### 4. `address already in use` / `10048`

Artinya:

- port websocket sedang dipakai proses lain

Biasanya terjadi jika service lama masih hidup.

### 5. `Invalid stops`

Artinya:

- broker menolak jarak stop loss yang terlalu dekat untuk harga saat itu

Solusi praktis:

- naikkan `Stop Loss Distance`
- lakukan `Preview` dan `Preflight` lagi

## Batas Fitur Saat Ini

Hal yang belum ada walaupun diusulkan di master brief:

- mode `DEV / MOCK MODE` yang terlihat jelas di UI
- reconnect overlay khusus saat MT5 hilang
- review sheet khusus saat akun berubah
- pengelolaan AI workspace, AI documents, dan AI context per akun
- pelokalan penuh ke istilah Indonesia di seluruh UI

Hal yang sudah ada sekarang:

- startup gate first-pass untuk `service -> MT5 -> Codex`

## Penutup

Aturan paling aman untuk operator baru:

- mulai dari demo
- mulai dari dry-run
- baca hasil `Preview`, `Preflight`, dan `Telemetry`
- jangan aktifkan live jika Anda belum paham status yang tampil
- hentikan runtime jika ada error berulang atau kondisi yang membingungkan
