# User Manual

## Untuk Siapa

Dokumen ini untuk operator non-teknis yang memakai desktop app Qt `bot-ea`.

Tujuan utamanya:

- memahami urutan kerja aplikasi
- mengetahui arti status di startup gate
- membedakan mode operator dan dev
- tahu apa yang terjadi saat MT5 hilang atau akun berubah

## Cara Menjalankan

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Dalam penggunaan normal:

- Anda tidak perlu menyalakan websocket service manual.
- App akan mencoba mengelola service lokal sendiri.
- Workspace utama akan tetap terkunci sampai dependency operator lolos.

## Dua Mode Aplikasi

### Operator Mode

Dipakai untuk supervised trading.

Syarat:

- MT5 aktif
- akun MT5 bisa dibaca
- AI runtime tersedia
- workspace AI tersedia
- dokumen AI tersedia
- context AI tersedia
- storage runtime tersedia

### Dev / Mock Mode

Dipakai untuk:

- tuning UI
- styling
- layout
- mock backend

Perilaku:

- bisa membuka workspace tanpa MT5
- bisa membuka workspace tanpa AI runtime
- tampil badge `DEV / MOCK MODE`

## Startup Gate

Saat mode operator dipakai, aplikasi memeriksa langkah berikut sebelum membuka workspace:

1. Service lokal
2. MetaTrader 5
3. Sesi MT5
4. Akun aktif
5. Simbol dasar
6. AI runtime
7. Workspace AI
8. Dokumen AI
9. Context / history
10. Storage
11. Resume state
12. Workspace utama

Kalau satu langkah gagal:

- aplikasi tetap berada di layar `Persiapan Sistem`
- status gagal tampil di panel status
- Anda bisa memperbaiki setting lalu klik `Coba Lagi`

## Arti Komponen AI Runtime

Di aplikasi ini, AI runtime bukan cuma command `codex`.

Yang dicek:

- `Command AI Runtime`
- `Workspace AI`
- `Dokumen AI`
- `Context Root`
- `Timeout`
- `Runtime DB`

Context disimpan per akun MT5, sehingga akun berbeda tidak mencampur memory kerja.

## Halaman Utama

Setelah gate lolos, sidebar menampilkan:

- `Dasbor`
- `Strategi`
- `Riwayat`
- `Log`
- `Pengaturan`

### Dasbor

Dipakai untuk melihat:

- status sistem
- ringkasan market
- ringkasan order
- batas risiko
- mode runtime

### Strategi

Dipakai untuk:

- mengatur parameter trading
- memilih model AI
- mengatur workspace/dokumen/context AI
- menjalankan tombol eksekusi

### Riwayat

Dipakai untuk:

- membaca telemetry run
- melihat validation summary
- meninjau hasil run sebelumnya

### Log

Dipakai untuk:

- membaca feed runtime
- melihat event sistem
- memantau tick terakhir dan status approval

### Pengaturan

Dipakai untuk melihat ringkasan:

- endpoint service
- command AI runtime
- workspace AI
- dokumen AI
- context root
- context akun aktif
- runtime DB

## Tombol Utama

### `Cek MT5`

Memeriksa:

- MT5 bisa diakses
- sesi MT5 aktif
- akun aktif terbaca
- simbol dasar siap dibaca

### `Cek AI Runtime`

Memeriksa:

- command AI runtime bisa dipanggil
- workspace AI ada
- dokumen AI ada
- context AI ada
- resume state akun siap

### `Refresh Data`

Memuat:

- snapshot market terbaru
- ringkasan order manual
- batas risiko

### `Cek Safety`

Menjalankan preflight broker dan guard internal sebelum order benar-benar dikirim.

### `Eksekusi Order`

Menjalankan order manual dari setup saat ini.

Kalau live belum aktif:

- hasilnya tetap bisa berupa dry-run

### `Mulai Bot`

Memulai runtime polling di backend.

Penting:

- ini tidak otomatis mengaktifkan live
- ini tidak otomatis membuka posisi

### `Berhenti Bot`

Menghentikan runtime aktif.

### `Aktifkan Live`

Mengubah runtime dari dry-run ke supervised live mode.

Tetap ada approval operator bila proposal live muncul.

### `Setujui Proposal` dan `Tolak Proposal`

Dipakai hanya saat order live menunggu keputusan operator.

### `Lihat Telemetri`

Memuat ulang telemetry, validation, dan lifecycle trading.

## Urutan Pakai Yang Aman

1. Buka MT5.
2. Login ke akun yang benar.
3. Jalankan Qt app.
4. Biarkan startup gate selesai.
5. Buka `Strategi`.
6. Review simbol, timeframe, modal, dan setting AI.
7. Klik `Refresh Data`.
8. Klik `Cek Safety`.
9. Klik `Mulai Bot`.
10. Biarkan beberapa cycle berjalan.
11. Review `Riwayat` dan `Log`.
12. Aktifkan live hanya kalau Anda siap melakukan approval manual.

## Saat MT5 Hilang

Jika MT5 hilang saat runtime tidak aktif:

- kontrol trading diblokir
- reconnect overlay muncul
- app akan mencoba cek MT5 lagi

Jika MT5 hilang saat runtime aktif:

- runtime masuk safe halt
- live dinonaktifkan
- approval pending dibersihkan
- Anda harus menyalakan MT5 lalu memulai bot lagi secara manual

## Saat Akun Berubah

Jika app mendeteksi fingerprint akun baru:

- trading diblokir
- kartu review akun muncul
- Anda bisa:
  - gunakan context akun yang sudah ada
  - buat context baru
  - batalkan dan kembali ke startup gate

Setelah akun baru diterima:

- context akun akan di-bind ulang
- bot tidak auto-start
- Anda harus memulai bot lagi manual

## Error Umum

### MT5 tidak tersedia

Arti:

- terminal belum dibuka
- terminal login belum siap
- koneksi IPC MT5 sedang putus

Tindakan:

1. Buka atau fokuskan MT5.
2. Pastikan akun sudah login.
3. Klik `Coba Lagi` atau tunggu reconnect.

### AI runtime tidak ditemukan

Arti:

- command `codex` tidak ada di `PATH`
- atau workspace/runtime path salah

Tindakan:

1. Periksa `Command AI Runtime`.
2. Periksa `Workspace AI`.
3. Pastikan `codex --version` berjalan di terminal.

### Context AI belum siap

Arti:

- folder context tidak ada
- atau tidak bisa ditulis

Tindakan:

1. Periksa `Context Root`.
2. Pastikan folder bisa dibuat/ditulis.
3. Jalankan ulang gate.

## Catatan Penting

- Bot tidak auto-start setelah aplikasi dibuka.
- Live tidak auto-enable.
- Context AI dipisah per akun.
- Jika kondisi membingungkan, hentikan bot lebih dulu lalu review `Log` dan `Riwayat`.
