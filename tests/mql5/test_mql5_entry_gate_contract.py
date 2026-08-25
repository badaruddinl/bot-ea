from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "mt5/Include/bot-ea/GoldEngineEntryGate.mqh"
RUNTIME = ROOT / "mt5/Include/bot-ea/GoldEngineRuntime.mqh"


def test_entry_gate_is_session_bound_and_fail_closed() -> None:
    gate = GATE.read_text(encoding="utf-8")
    runtime = RUNTIME.read_text(encoding="utf-8")

    assert "m_session_id" in gate
    assert "parts[4]==m_session_id" in gate
    assert 'parts[5]=="ENABLED"' in gate
    assert "m_enabled=false" in gate
    assert "MQL_TESTER" in gate
    assert "if(!m_entry_gate.Enabled())" in runtime
    assert '"NEW_ENTRY_GATE_DISABLED"' in runtime
    assert "RefreshEntryGate(raw_tick.time)" in runtime
    assert "RefreshEntryGate(server_time)" in runtime


def test_entry_gate_does_not_disable_position_management_authority() -> None:
    runtime = RUNTIME.read_text(encoding="utf-8")
    submit = runtime.index("void SubmitSignalPlan")
    modify = runtime.index("bool ModifyOwnedPosition")
    close = runtime.index("bool CloseOwnedPosition")

    assert runtime.index("if(!m_entry_gate.Enabled())", submit, modify) > submit
    assert "m_entry_gate.Enabled()" not in runtime[modify:close]
