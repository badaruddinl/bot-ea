# Runbook Desktop Runtime

## Tujuan

Runbook ini menjelaskan desktop runtime Qt yang saat ini dipakai oleh `bot-ea`.

Dokumen ini ditujukan untuk:

- developer yang memelihara stack desktop/runtime
- operator yang menjalankan sesi MT5 supervised, demo, atau dry-run

## Postur Operasional

Sudah didukung:

- operasi desktop supervised
- flow live yang digate oleh operator
- proteksi reconnect MT5
- review saat ganti akun
- persiapan context AI per akun

Belum didukung:

- autonomy tanpa operator
- packaging setara installer
- otomasi lifecycle close/modify yang penuh

## Arsitektur Desktop

Komponen utama:

1. `src/bot_ea/qt_app.py`
2. `src/bot_ea/websocket_service.py`
3. `src/bot_ea/desktop_runtime.py`
4. `src/bot_ea/operator_state.py`
5. `src/bot_ea/mt5_adapter.py`
6. `src/bot_ea/runtime_store.py`

Model runtime:

- Qt app adalah permukaan desktop utama
- app dapat menyalakan backend websocket lokal sendiri
- command backend membuka probe readiness, helper eksekusi manual, kontrol runtime, dan telemetri
- state operator dipersistkan di `runtime_data/`

## Model Peluncuran

Peluncuran yang disarankan:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-qt-gui.ps1
```

Peluncuran backend khusus debug:

```powershell
cd D:\luthfi\project\bot-ea
powershell -ExecutionPolicy Bypass -File .\scripts\run-websocket-service.ps1
```

## Kontrak Startup Gate

Mode operator saat ini memeriksa:

1. `probe_service_ready`
2. `probe_mt5_process`
3. `probe_mt5_session`
4. `probe_account_fingerprint`
5. `probe_symbol_baseline`
6. `probe_ai_runtime`
7. `probe_ai_workspace`
8. `probe_ai_documents`
9. `probe_ai_context_store`
10. `validate_storage`
11. `build_resume_state`

Main workspace baru dibuka setelah semua langkah itu lolos.

Mode dev:

- melewati operator gate
- langsung membuka workspace
- mengatur badge UI ke `DEV / MOCK MODE`

## Permukaan Command Backend

Permukaan command saat ini mencakup:

- `probe_service_ready`
- `load_runtime_settings`
- `save_runtime_settings`
- `probe_mt5_process`
- `probe_mt5_session`
- `probe_account_fingerprint`
- `probe_symbol_baseline`
- `probe_ai_runtime`
- `probe_ai_workspace`
- `probe_ai_documents`
- `probe_ai_context_store`
- `validate_storage`
- `build_resume_state`
- `refresh_manual`
- `preflight_manual`
- `execute_manual`
- `start_runtime`
- `stop_runtime`
- `set_live_enabled`
- `approve_pending`
- `reject_pending`
- `load_telemetry`

## Persistensi State Operator

File yang dibuat di bawah `runtime_data/`:

- `runtime_settings.json`
- `app_settings.json`
- `account_context_map.json`
- `runtime_state.json`

Account contexts are created under `ai_context/<broker>_<server>_<login>/`.

File yang dihasilkan mencakup:

- `profile.yaml`
- `memory/latest_summary.md`
- `memory/open_issues.md`
- `memory/last_session.json`
- `resume/resume_prompt.md`
- `documents/broker_notes.md`
- `documents/operator_notes.md`

Peran masing-masing file:

- `runtime_state.json`: snapshot operator lintas sesi untuk akun/context aktif terakhir, `run_id`, state runtime, alasan berhenti, dan metadata runtime yang ditulis backend
- `memory/last_session.json`: catatan kelanjutan sesi per akun yang ditulis oleh event lifecycle backend
- `resume/resume_prompt.md`: scaffold prompt yang dapat dipakai ulang untuk context akun; file ini tetap ada setelah restart tetapi tidak auto-start runtime

## Siklus Runtime

### Start supervised normal

1. startup gate lolos
2. operator menekan `Mulai Bot`
3. backend menyalakan runtime thread
4. `run_id` dibuat
5. event runtime dikirim balik melalui websocket
6. telemetri ditulis ke SQLite

### MT5 terputus saat idle

- UI shows reconnect overlay
- kontrol trading dinonaktifkan
- log/riwayat/pengaturan tetap bisa diakses
- cek MT5 periodik tetap berjalan

### MT5 terputus saat runtime aktif

- runtime masuk ke safe halt
- live mode dinonaktifkan
- pending approval dibersihkan
- operator harus menyambungkan MT5 lagi dan memulai bot secara manual

Kontrak kelanjutan sesi setelah halt ini:

- dipertahankan: `runtime_state.json` menyimpan fingerprint akun aktif, mapping context, `last_run_id`, `last_runtime_state=halted`, dan `last_shutdown_reason`
- dipertahankan: context akun yang terikat tetap menyimpan `memory/last_session.json`, `resume/resume_prompt.md`, profile, ringkasan, daftar issue, dan catatan
- dibuang: runtime thread di memori, state live-enabled sebagai kontrol aktif, payload pending approval, dan approval key yang sedang armed
- aturan restart: operator harus melewati readiness lagi bila perlu dan menekan `Mulai Bot` secara eksplisit; live tetap mati sampai diaktifkan ulang manual

### Fingerprint akun berubah

- UI membuka kartu review akun
- kontrol trading tetap diblokir
- operator dapat memakai context yang sudah dipetakan atau membuat yang baru
- runtime tidak di-restart otomatis

Kontrak kelanjutan sesi setelah review akun:

- dipertahankan: context akun sebelumnya tetap ada di disk tanpa diubah
- dipertahankan: setelah review disetujui, context yang dipilih atau baru dibuat disimpan sebagai mapping untuk fingerprint baru
- dipertahankan: context yang dipilih tetap menyimpan `resume_prompt.md`, `last_session.json`, ringkasan, issue, dan catatan untuk run supervised berikutnya
- dibuang: sesi runtime aktif lama tidak ikut pindah ke akun baru, dan pending approval/live state dari run yang terputus tetap dibersihkan
- aturan restart: setelah review diterima, app kembali ke flow readiness dan operator harus memulai runtime baru secara manual

## Semantik Readiness

### MT5

Siap berarti:

- terminal can be reached
- session is readable
- fingerprint akun stabil
- symbol baseline bisa dibaca

### AI Runtime

Siap berarti:

- command runtime bisa dipanggil
- path workspace ada
- path dokumen ada
- root context ada dan bisa ditulis
- resume state bisa dibind ke akun MT5 aktif

### Storage

Siap berarti:

- path DB runtime bisa dibuat
- metadata runtime bisa ditulis

## Telemetri SQLite

Telemetri tetap disimpan di `runtime_store.py` dan mencakup:

- runs
- polling cycles
- market snapshots
- AI decisions
- risk guard events
- execution events
- position events
- stop events
- runtime logs

## Gap Yang Masih Tersisa

Yang masih tertinggal setelah pass implementasi ini:

- manajemen lifecycle close/modify yang otonom
- drift monitoring yang lebih kaya dan kebijakan recovery unattended
- distribusi desktop yang sudah ter-package
- wiring prompt AI yang lebih dalam daripada readiness/persistensi context saat ini

## File Terkait

- [README.md](D:/luthfi/project/bot-ea/README.md)
- [docs/user-manual.md](D:/luthfi/project/bot-ea/docs/user-manual.md)
- [docs/project-handoff.md](D:/luthfi/project/bot-ea/docs/project-handoff.md)
- [src/bot_ea/qt_app.py](D:/luthfi/project/bot-ea/src/bot_ea/qt_app.py)
- [src/bot_ea/operator_state.py](D:/luthfi/project/bot-ea/src/bot_ea/operator_state.py)
