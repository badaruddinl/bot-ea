from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUTBOX = ROOT / "mt5/Include/bot-ea/GoldEngineOutbox.mqh"
RUNTIME = ROOT / "mt5/Include/bot-ea/GoldEngineRuntime.mqh"
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldEngineOutboxHarness.mq5"


def test_outbox_is_profile_specific_append_only_and_shared_readable() -> None:
    source = OUTBOX.read_text(encoding="utf-8")

    assert '"bot-ea\\\\spool\\\\"+profile.profile_id+".jsonl"' in source
    assert "FILE_READ|FILE_WRITE" in source
    assert "FILE_SHARE_READ|FILE_SHARE_WRITE|FILE_COMMON" in source
    assert "FileSeek(handle,0,SEEK_END)" in source
    assert "FileWriteString(handle,line)" in source
    assert "FileFlush(handle)" in source


def test_runtime_emits_transitions_but_never_writes_spool_on_every_tick() -> None:
    source = RUNTIME.read_text(encoding="utf-8")
    tick_body = source.split("void OnTick(void)", maxsplit=1)[1].split(
        "void Deinitialize", maxsplit=1
    )[0]

    for event_type in (
        "ENGINE_STARTED",
        "PROFILE_VALIDATED",
        "ENTRY_READY",
        "ORDER_SUBMITTED",
        "POSITION_OPENED",
        "POSITION_MODIFIED",
        "POSITION_CLOSED",
        "ENGINE_ERROR",
        "RECOVERY_COMPLETED",
    ):
        assert f'EmitTransition("{event_type}"' in source
    assert "FileWrite" not in tick_body
    assert "FileOpen" not in tick_body


def test_native_harness_proves_profile_routing_without_order_authority() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "goldi_audience=goldi_approved" in source
    assert "goldm_audience=admin_only" in source
    assert "order_authority=DISABLED" in source
    assert "G16_OUTBOX" in source
