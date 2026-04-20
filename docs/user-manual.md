# User Manual

## Untuk Siapa Dokumen Ini

Dokumen ini dibuat untuk user/operator yang tidak ingin membaca detail teknis kode.

Tujuannya sederhana:

- tahu cara membuka aplikasi
- tahu tombol mana yang harus diklik
- tahu arti status yang tampil
- tahu kapan aman lanjut
- tahu kapan harus berhenti

Dokumen ini tidak menganggap Anda seorang programmer.

## Apa Fungsi Aplikasi Ini

Aplikasi desktop `bot-ea` membantu Anda:

- memeriksa apakah MT5 siap dipakai
- memeriksa apakah `codex-cli` siap dipakai
- menjalankan bot di background
- melihat saran dan log hasil bot
- mengawasi sebelum order live benar-benar dikirim

Hal penting:

- aplikasi ini belum ditujukan untuk trading live tanpa pengawasan
- mode yang paling aman sekarang adalah `supervised demo test`

## Sebelum Mulai

Lakukan ini dulu:

1. Buka `MetaTrader 5`.
2. Login ke akun yang benar.
3. Pastikan simbol yang ingin dipakai ada, misalnya `EURUSD`.
4. Pastikan `codex` bisa dipanggil dari terminal.
5. Jalankan aplikasi desktop.

Checklist cepat:

- MT5 terbuka
- akun sudah login
- simbol tersedia
- `codex-cli` terpasang
- mulai dari `dry-run` dulu

## Cara Menjalankan Aplikasi

Cara paling mudah di Windows:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-desktop-gui.ps1
```

## Kenali Bagian Layar

### 1. Pengaturan Trading

Bagian ini berisi:

- `Symbol`
- `Timeframe`
- `Style`
- `Stop Points`
- `Allocation Mode`
- `Allocation`
- `Side`
- `Runtime DB`

Arti sederhananya:

- `Symbol`: instrumen yang dipakai, misalnya `EURUSD`
- `Timeframe`: kerangka waktu, misalnya `M15`
- `Style`: gaya trading
- `Stop Points`: jarak stop untuk sizing/risk
- `Allocation`: modal yang diizinkan dipakai bot
- `Runtime DB`: file log/catatan bot

### 2. Pengaturan Codex

Bagian ini berisi:

- `Codex CLI`
- `Codex Model`
- `Codex CWD`
- `Poll Interval (s)`

Arti sederhananya:

- `Codex CLI`: nama executable Codex, biasanya cukup `codex`
- `Codex Model`: model AI yang dipakai, biasanya boleh dikosongkan
- `Codex CWD`: folder kerja Codex
- `Poll Interval`: jarak waktu bot mengecek market lagi

Kalau tidak paham:

- biarkan `Codex CLI = codex`
- biarkan `Codex Model` kosong
- isi `Codex CWD` ke folder project

### 3. Status Kesiapan

Bagian ini menunjukkan:

- status MT5
- status Codex CLI
- status runtime background
- run yang sedang aktif
- status approval order live

### 4. Tombol Utama

Tombol yang paling penting:

- `Check MT5`
- `Load Codex`
- `Play Runtime`
- `Stop Runtime`
- `Enable Live` / `Disable Live`
- `Approve Pending`
- `Reject Pending`
- `Refresh`
- `Preflight`
- `Execute`
- `Load Telemetry`

## Arti Tombol

### `Check MT5`

Fungsi:

- mengecek apakah MT5 siap
- membaca akun, harga, dan simbol

Gunakan ini setiap kali memulai sesi.

### `Load Codex`

Fungsi:

- mengecek apakah `codex-cli` bisa dipakai

Gunakan ini sebelum `Play Runtime`.

### `Play Runtime`

Fungsi:

- memulai bot di background

Ini bukan berarti langsung trading live.

### `Stop Runtime`

Fungsi:

- menghentikan bot background

Gunakan ini jika ingin berhenti, mengubah setting, atau ada error.

### `Enable Live`

Fungsi:

- mengizinkan bot mengirim order sungguhan

Jangan aktifkan ini pada pengujian pertama.

### `Approve Pending`

Fungsi:

- menyetujui proposal order live yang sedang menunggu persetujuan

### `Reject Pending`

Fungsi:

- menolak proposal order live yang sedang menunggu persetujuan

### `Refresh`

Fungsi:

- mengambil data harga dan akun terbaru

### `Preflight`

Fungsi:

- mengecek apakah setup/order saat ini lolos pemeriksaan risiko dan broker

Ini bukan jaminan profit.

### `Execute`

Fungsi:

- mencoba menjalankan order manual berdasarkan setting saat ini

Gunakan dengan hati-hati.

### `Load Telemetry`

Fungsi:

- memuat log hasil bot
- menampilkan ringkasan runtime, health, event order, dan warning

## Urutan Pakai yang Disarankan

Ikuti urutan ini:

1. Isi `Symbol`, `Timeframe`, `Style`, `Stop Points`.
2. Pilih `Allocation Mode` dan isi nilai modal.
3. Pastikan `Runtime DB` benar.
4. Pastikan `Codex CLI` dan `Codex CWD` benar.
5. Klik `Check MT5`.
6. Jika MT5 siap, klik `Load Codex`.
7. Jika Codex siap, klik `Refresh`.
8. Klik `Preflight`.
9. Jika hasil aman, klik `Play Runtime`.
10. Biarkan bot berjalan beberapa cycle.
11. Klik `Load Telemetry`.
12. Tetap di mode `dry-run` dulu.
13. Hanya jika benar-benar perlu, gunakan `Enable Live`.
14. Jika muncul proposal live, baca dulu lalu pilih `Approve Pending` atau `Reject Pending`.

## Alur Penggunaan Paling Aman

Untuk user baru:

1. Jalankan aplikasi.
2. Klik `Check MT5`.
3. Klik `Load Codex`.
4. Klik `Refresh`.
5. Klik `Preflight`.
6. Klik `Play Runtime`.
7. Jangan aktifkan live dulu.
8. Klik `Load Telemetry`.
9. Lihat apakah bot sehat dan tidak banyak error/rejection.

Kalau semua masih normal, baru pertimbangkan langkah berikutnya.

## Arti Status Penting

### Status umum

- `Ready`
  Artinya aplikasi siap dibuka, tapi belum tentu MT5/Codex siap.

- `MT5 readiness checked`
  Artinya pengecekan MT5 selesai.

- `codex-cli ready`
  Artinya Codex berhasil dikenali.

- `Background runtime starting`
  Artinya bot background sedang mulai jalan.

- `desktop runtime started`
  Artinya bot background sudah aktif.

- `desktop runtime stopped`
  Artinya bot sudah dihentikan.

### Status hasil manual

- `Snapshot refreshed`
  Data harga dan akun berhasil diambil.

- `Preflight complete`
  Pengecekan sebelum order selesai.

- `Execution attempted`
  Sistem sudah mencoba menjalankan aksi manual.

### Status yang perlu diperhatikan

- `MT5 probe failed`
  Aplikasi gagal membaca MT5.

- `codex-cli probe failed`
  Aplikasi gagal memakai Codex.

- `Runtime failed to start`
  Bot background gagal mulai.

- `MT5 terminal blocks live trading`
  MT5 masih menolak live trading.

## Arti Hasil di Panel Output

Beberapa kata penting:

- `accepted=true`
  Setup diterima oleh sizing/risk.

- `accepted=false`
  Setup ditolak.

- `status=PRECHECK_OK`
  Pemeriksaan broker awal lolos.

- `status=PRECHECK_REJECTED`
  Broker menolak request pada tahap awal.

- `status=GUARD_REJECTED`
  Risk guard internal menolak.

- `status=DRY_RUN_OK`
  Simulasi lolos, belum kirim order sungguhan.

- `status=FILLED`
  Order berhasil terisi.

- `status=REJECTED`
  Order ditolak/gagal.

- `warning=...`
  Ada hal yang perlu diperhatikan.

- `rejection_reason=...`
  Alasan utama penolakan.

## Cara Membaca Telemetry

Saat klik `Load Telemetry`, fokus lihat ini:

- `run_id`
- `status`
- `last_cycle`
- `last_action`
- `stop_reason`
- `reject_rate`
- `risk_guard`
- `recent_positions`
- `recent_execution_events`
- `recent_rejections`
- `validation_summary`
- `execution_quality_run_scoped`

Arti sederhananya:

- `run_id`: nomor sesi bot
- `last_action`: keputusan bot terakhir
- `reject_rate`: seberapa sering bot ditolak
- `recent_positions`: posisi yang dibuka/ditutup
- `recent_execution_events`: jejak percobaan order
- `validation_summary`: ringkasan hasil trading pada run itu

## Arti Approval Flow

Jika live mode aktif, bot tetap tidak langsung mengirim order live.

Urutannya:

1. Bot membuat proposal.
2. Risk guard memeriksa.
3. Broker preflight memeriksa.
4. GUI menunggu persetujuan operator.
5. Anda pilih:
   - `Approve Pending`
   - `Reject Pending`

Arti penting:

- `Approve Pending` bukan berarti trading otomatis selamanya
- persetujuan berlaku untuk proposal yang cocok
- jika proposal berubah, Anda harus tinjau lagi

## Kapan Boleh Lanjut

Anda boleh lanjut jika:

- `Check MT5` berhasil
- `Load Codex` berhasil
- `Refresh` berhasil
- `Preflight` menunjukkan hasil aman
- tidak ada rejection besar
- tidak ada warning yang jelas-jelas berbahaya

Untuk live:

- hanya lanjut jika Anda benar-benar paham risikonya
- pastikan mode masih `supervised`

## Kapan Harus Berhenti

Berhenti jika:

- MT5 gagal dibaca
- Codex gagal dibaca
- `accepted=false`
- `GUARD_REJECTED`
- `PRECHECK_REJECTED`
- spread terlalu lebar
- reject rate mulai tinggi
- output panel menunjukkan error berulang
- Anda tidak paham proposal order yang sedang menunggu approval

Kalau ragu:

- klik `Stop Runtime`

## Error Paling Umum dan Solusinya

### 1. `MT5 probe failed`

Kemungkinan:

- MT5 belum dibuka
- akun belum login
- simbol tidak tersedia

Yang harus dilakukan:

1. buka MT5
2. login ulang
3. cek simbol
4. ulang `Check MT5`

### 2. `codex-cli probe failed`

Kemungkinan:

- `codex` tidak ada di PATH
- `Codex CWD` salah

Yang harus dilakukan:

1. cek field `Codex CLI`
2. cek field `Codex CWD`
3. tes `codex --version` di terminal
4. ulang `Load Codex`

### 3. `Runtime failed to start`

Kemungkinan:

- MT5/Codex belum ready
- input salah
- DB path bermasalah

Yang harus dilakukan:

1. ulang `Check MT5`
2. ulang `Load Codex`
3. cek `Runtime DB`
4. cek angka `Stop Points`, `Allocation`, `Poll Interval`

### 4. `MT5 terminal blocks live trading`

Kemungkinan:

- izin trading di terminal belum aktif
- akun broker tidak mengizinkan

Yang harus dilakukan:

1. cek izin trading di MT5
2. cek akun broker
3. ulang `Check MT5`

### 5. `Runtime DB not found`

Kemungkinan:

- bot belum pernah dijalankan
- path log salah

Yang harus dilakukan:

1. cek field `Runtime DB`
2. klik `Play Runtime`
3. tunggu 1-2 cycle
4. klik `Load Telemetry` lagi

## Arti Allocation Mode

Bagian ini penting karena sering membingungkan.

- `fixed_cash`
  Bot hanya memakai nominal uang tertentu.

- `percent_equity`
  Bot memakai persentase tertentu dari equity akun.

- `full_equity`
  Bot memakai seluruh equity sebagai basis hitung.

Contoh:

- jika pilih `fixed_cash = 250`, bot menghitung sizing dari modal 250
- jika pilih `percent_equity = 35`, bot menghitung dari 35% equity akun

Ini bukan berarti bot pasti membuka order sebesar angka itu.

## Aturan Praktis untuk User Baru

Lakukan:

- mulai dari akun demo
- mulai dari dry-run
- baca hasil `Preflight`
- baca hasil `Load Telemetry`
- hentikan bot jika bingung

Jangan lakukan:

- jangan aktifkan live pada percobaan pertama
- jangan klik `Approve Pending` jika Anda tidak paham proposalnya
- jangan abaikan warning/rejection berulang
- jangan anggap `Preflight complete` berarti pasti untung

## Contoh Skenario Normal

Contoh alur sehat:

1. `Check MT5` -> berhasil
2. `Load Codex` -> berhasil
3. `Refresh` -> harga tampil
4. `Preflight` -> lolos
5. `Play Runtime` -> run aktif
6. `Load Telemetry` -> data muncul
7. tetap di dry-run

## Penutup

Aplikasi ini belum ditujukan sebagai tombol “jalan otomatis tanpa pengawasan”.

Peran Anda sebagai operator tetap penting:

- memeriksa kesiapan
- membaca proposal
- memutuskan setuju atau menolak
- menghentikan bot jika ada hal yang tidak wajar

Jika Anda ragu, pilihan yang benar adalah:

- jangan kirim order live
- tetap di dry-run
- klik `Stop Runtime`
