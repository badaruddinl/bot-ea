# bot-ea

Repository engine trading MetaTrader 5 untuk dua profile yang terisolasi:

- \`GOLDI\` — simbol \`GOLD.i#\`, akun DEMO, magic \`26081911\`;
- \`GOLDM\` — simbol \`GOLDm#\`, production REAL, magic \`26081912\`.

Repository ini bukan aplikasi desktop dan tidak menyediakan UI Qt/Tk atau
layanan WebSocket. Decision engine, execution guard, state recovery, audit, dan
bridge observability berjalan sebagai engine/worker atau langsung di EA MQL5.

## Arsitektur

- \`src/gold_engine_core/\` — kontrak pure, Revised BUY, Bear SELL, causal
  replay, execution guard, restart parity, dan validation evidence.
- \`src/gold_portfolio/\` — portfolio worker Python selama masa reference dan
  migrasi.
- \`src/gold_orchestrator/\` — orkestrasi worker profile.
- \`src/goldm_revised/\` dan \`src/goldm_bear/\` — compatibility/reference
  surface yang menggunakan rule core.
- \`config/profiles/\` — manifest profile-locked dan fingerprint.
- \`config/validation_profiles/\` — binding validation fail-closed.
- \`mql5/\` — target source dan shared core EA profile-locked pada gate G11+.

Python dipertahankan sebagai reference sampai parity MQL5 tersertifikasi.
Python dan EA tidak boleh menjadi order authority bersamaan untuk profile,
account, symbol, dan magic yang sama.

## Instalasi pengembangan

\`\`\`powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[live,dev]"
\`\`\`

Optional research dependencies:

\`\`\`powershell
.\.venv\Scripts\python.exe -m pip install -e ".[research]"
\`\`\`

## Verifikasi

\`\`\`powershell
.\.venv\Scripts\python.exe -m ruff format --check src scripts tests
.\.venv\Scripts\python.exe -m ruff check src scripts tests
.\.venv\Scripts\python.exe -m pytest -q
\`\`\`

Default \`pytest\` menjalankan unit/integration suite cepat. Full release
regression, termasuk historical research matrix dan deployment sealing:

\`\`\`powershell
.\.venv\Scripts\python.exe -m pytest -q -m "slow or not slow"
\`\`\`

Incremental gate:

\`\`\`powershell
.\.venv\Scripts\python.exe scripts\quality_gate.py --base <audited-sha> --head HEAD
\`\`\`

## Keselamatan

- REAL order authority tidak pernah aktif otomatis.
- GOLDm REAL hanya boleh digunakan untuk probe metadata/tick/bar read-only
  selama engineering; \`orders_sent=0\` wajib dibuktikan.
- GOLDm execution engineering menggunakan Strategy Tester terisolasi.
- Wrong symbol/account/server/mode/profile/magic harus fail closed.
- Telegram, database, dan bridge tidak berada pada broker-critical path.
- Tidak ada fallback identity atau state antara GOLDI dan GOLDM.

Target, gate G00–G21, ledger, dan definition of done berada di
\`BOT-EA-CODEX-GOAL.md\`. Instruksi repository berada di \`AGENTS.md\`.
