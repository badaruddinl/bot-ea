from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TELEGRAM_SURFACES = (
    ROOT / "src/gold_event_bridge/bridge.py",
    ROOT / "src/gold_orchestrator/runtime.py",
    ROOT / "src/goldm_signal/notify/telegram.py",
)


def test_active_telegram_surfaces_do_not_contain_indonesian_user_copy() -> None:
    blocked_copy = (
        "Permintaan",
        "Akses",
        "Tidak ada",
        "Belum ada",
        "Matikan",
        "Hidupkan",
        "Yakin",
        "Batal",
        "Diproses",
        "KONFIRMASI",
        "NOTIFIKASI",
        "DIBLOKIR",
        "Tanpa nama",
        "Jenis chat",
        "Strategi:",
        "Harga open",
        "Harga close",
        "Ditutup oleh",
        "Durasi:",
        "Waktu server",
        "Alasan:",
        " hari",
        " jam",
        " menit",
        " detik",
    )

    for path in TELEGRAM_SURFACES:
        source = path.read_text(encoding="utf-8")
        for value in blocked_copy:
            assert value not in source, f"Indonesian Telegram copy remains in {path}: {value}"


def test_trade_messages_expose_strategy_mode_and_trade_reason() -> None:
    bridge = (ROOT / "src/gold_event_bridge/bridge.py").read_text(encoding="utf-8")

    assert "Strategy mode:" in bridge
    assert "Trade reason:" in bridge
    assert "Execution status:" in bridge
    assert "Event status:" in bridge
