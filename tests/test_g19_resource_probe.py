from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/g19-windows-resource-probe.ps1"


def test_resource_probe_captures_required_components_and_storage() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for value in (
        "GOLDI",
        "GOLDM",
        "BRIDGE",
        "rss_bytes",
        "private_bytes",
        "handle_count",
        "thread_count",
        "database_bytes",
        "wal_bytes",
        "goldi_spool_bytes",
        "goldm_spool_bytes",
        "heartbeat_generation",
    ):
        assert value in source


def test_resource_probe_is_read_only_and_requires_disabled_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'heartbeat.order_authority -ne "DISABLED"' in source
    for forbidden in (
        "OrderSend",
        "order_send",
        "CTrade",
        "Restart-Computer",
        "Stop-Process",
        "Invoke-WebRequest",
    ):
        assert forbidden not in source
