from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "mt5/Include/bot-ea/GoldEngineRuntime.mqh"
BROKER = ROOT / "mt5/Include/bot-ea/GoldEngineExecutionBroker.mqh"


def test_runtime_records_four_native_latency_stages_on_existing_transition() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    broker = BROKER.read_text(encoding="utf-8")

    for field in (
        "bar_close_to_detection_ms",
        "detection_to_decision_us",
        "entry_ready_to_submit_us",
        "submit_to_broker_ack_us",
    ):
        assert field in runtime
    assert "GetMicrosecondCount" in runtime
    assert "GetMicrosecondCount" in broker


def test_runtime_tester_override_is_derived_only_from_mql_tester() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert "plan.engineering_tester=(bool)MQLInfoInteger(MQL_TESTER);" in runtime
    assert 'EmitTransition("POSITION_OPENED"' in runtime


def test_latency_telemetry_adds_no_tick_path_io_or_new_transition() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    on_tick = runtime.split("void OnTick(void)", 1)[1].split("void Deinitialize", 1)[0]

    for forbidden in ("FileOpen", "Database", "WebRequest", "SendNotification"):
        assert forbidden not in on_tick
    assert "EmitTransition" not in on_tick
