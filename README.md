# bot-ea

Desktop workspace for supervised MetaTrader 5 trading with:

- Python risk sizing and execution guards
- MT5 adapter and broker preflight
- Codex-backed runtime decisions
- SQLite telemetry and validation
- websocket transport
- Qt operator app with dependency gate

This repository is not unattended live-trading software. It is an operator-first desktop runtime with explicit approval and halt behavior.

## Status Produk Saat Ini

Sudah diterapkan:

- service websocket lokal yang dikelola app
- startup gate mode operator sebelum workspace dibuka
- mode `operator` dan `dev / mock` yang eksplisit
- rantai readiness MT5:
  - service
  - MT5 process
  - MT5 session
  - account fingerprint
  - symbol baseline
- rantai readiness AI:
  - runtime command
  - AI workspace
  - AI documents
  - AI context root
  - runtime storage
  - account-scoped resume state
- reconnect overlay dan safe halt saat MT5 hilang
- flow review ganti akun dengan context binding per akun
- start/stop runtime supervised, toggle live, approval, rejection, dan review telemetri

Masih belum selesai:

- autonomy tanpa operator
- otomasi lifecycle close/modify yang penuh
- distribusi packaging/installer
- drift monitoring di luar telemetri dan validasi saat ini

## Menjalankan Aplikasi

Jalankan normal di Windows:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Default operator:

- Qt app adalah entrypoint utama
- app dapat menyalakan backend websocket lokal sendiri
- workspace utama tetap terkunci sampai dependency gate operator lolos
- bot runtime tidak auto-start setelah gate lolos

## Mode Aplikasi

### Operator Mode

Aturan:

- MT5 wajib tersedia
- akun MT5 yang bisa dibaca wajib tersedia
- AI runtime wajib tersedia
- AI workspace/dokumen/konteks/storage wajib tersedia
- workspace tetap terkunci sampai semua cek lolos

### Dev / Mock Mode

Aturan:

- melewati dependency MT5 dan AI
- membuka workspace utama untuk tuning UI dan pengujian mock
- menampilkan badge `DEV / MOCK MODE` yang jelas

## Startup Gate

Urutan startup operator saat ini:

1. Service lokal
2. MetaTrader 5
3. Sesi MT5
4. Akun aktif
5. Simbol dasar
6. AI runtime
7. Workspace AI
8. Dokumen AI
9. Konteks AI
10. Storage
11. Resume state
12. Workspace utama

Perilaku:

- jika satu langkah gagal, app tetap berada di gate
- gate menampilkan status yang mudah dibaca, bukan spam popup
- operator bisa retry manual atau pindah ke mode dev

## MT5 Putus Dan Ganti Akun

### MT5 hilang saat idle

- kontrol trading dinonaktifkan
- reconnect overlay ditampilkan
- telemetri dan diagnostik tetap bisa diakses
- app terus mengulang cek MT5 dari workspace

### MT5 hilang saat runtime aktif

- runtime masuk ke safe halt
- live mode dinonaktifkan
- pending approval dibersihkan
- operator harus menyambungkan kembali MT5 dan menyalakan bot secara manual

### Fingerprint akun berubah

- app memblokir kontrol trading
- kartu review akun ditampilkan
- operator bisa memakai context yang ada atau membuat context akun baru
- runtime harus dijalankan manual lagi setelah review

### Kontrak Kelanjutan Sesi Setelah Safe Halt Atau Ganti Akun

Dipertahankan setelah restart:

- `runtime_data/runtime_state.json` menyimpan fingerprint MT5 aktif terakhir, `context_key`, `context_path`, `last_run_id`, `last_runtime_state`, dan `last_shutdown_reason`
- `ai_context/<account>/memory/last_session.json` menyimpan metadata run terakhir per akun seperti simbol, timeframe, gaya trading, mode terakhir, dan alasan berhenti
- context akun yang dipilih tetap ada di disk, termasuk `profile.yaml`, `memory/latest_summary.md`, `memory/open_issues.md`, `resume/resume_prompt.md`, dan catatan operator/broker
- setelah review akun disetujui, context yang dipilih atau baru dibuat menjadi mapping tersimpan untuk fingerprint MT5 tersebut

Sengaja dibuang atau dipaksa kembali ke default aman:

- thread/sesi runtime aktif tidak pernah bertahan setelah restart; operator harus memulainya lagi secara manual
- live mode dipaksa mati saat safe halt dan tidak pernah aktif otomatis pada launch berikutnya, bahkan jika run sebelumnya berakhir dalam mode live
- pending live approval dan approval key yang sedang armed dibersihkan; proposal order live harus dibuat ulang setelah restart
- state reconnect overlay dan state UI account-review hanya guard UI sementara, bukan runtime state yang dipersistkan
- ganti akun tidak auto-resume trading; app kembali ke review readiness sebelum kontrol trading dibuka lagi

## Tata Letak AI Runtime

Aplikasi desktop sekarang memperlakukan readiness AI runtime sebagai lebih dari satu executable.

Folder yang direkomendasikan:

```text
bot-ea/
  ai_workspace/
  ai_documents/
  ai_context/
  runtime_data/
```

Data persisten sekarang mencakup:

- `runtime_data/runtime_settings.json`
- `runtime_data/app_settings.json`
- `runtime_data/account_context_map.json`
- `runtime_data/runtime_state.json`

`runtime_state.json` adalah snapshot operator lintas sesi. File ini mencatat fingerprint akun aktif terakhir, context akun yang dipilih, identitas run terakhir, state runtime, alasan berhenti, dan parameter runtime terbaru yang ditulis backend.

Context akun dibuat di bawah `ai_context/<broker>_<server>_<login>/` dengan:

- `profile.yaml`
- `memory/latest_summary.md`
- `memory/open_issues.md`
- `memory/last_session.json`
- `resume/resume_prompt.md`
- `documents/broker_notes.md`
- `documents/operator_notes.md`

`memory/last_session.json` adalah file kelanjutan sesi per akun. File ini menyimpan metadata run terbaru untuk akun MT5 tertentu, tetapi tidak mengaktifkan ulang runtime dengan sendirinya.

## Alur Operator

Alur supervised yang direkomendasikan:

1. Buka MT5 dan login ke akun yang benar.
2. Jalankan Qt app.
3. Biarkan startup gate memvalidasi dependency.
4. Tinjau halaman `Strategi`.
5. Klik `Refresh Data`.
6. Klik `Cek Safety`.
7. Klik `Mulai Bot`.
8. Jika perlu, klik `Aktifkan Live`.
9. Setujui atau tolak hanya saat proposal live memang sedang pending.
10. Tinjau telemetri di `Riwayat` dan `Log`.

Aturan runtime penting:

- bot runtime tidak pernah auto-start hanya karena app diluncurkan
- live mode tidak pernah aktif otomatis

## File Penting

Dokumen:

- [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
- [docs/desktop-runtime-runbook.md](D:/luthfi/project/bot-ea/docs/desktop-runtime-runbook.md)
- [docs/project-handoff.md](D:/luthfi/project/bot-ea/docs/project-handoff.md)
- [docs/progress-summary.md](D:/luthfi/project/bot-ea/docs/progress-summary.md)

Kode:

- [src/bot_ea/qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
- [src/bot_ea/websocket_service.py](D:/luthfi/project/bot-ea/src/bot_ea/websocket_service.py)
- [src/bot_ea/desktop_runtime.py](D:/luthfi/project/bot-ea/src/bot_ea/desktop_runtime.py)
- [src/bot_ea/operator_state.py](D:/luthfi/project/bot-ea/src/bot_ea/operator_state.py)
- [src/bot_ea/mt5_adapter.py](D:/luthfi/project/bot-ea/src/bot_ea/mt5_adapter.py)
