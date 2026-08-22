from pathlib import Path

import pytest

from scripts.run_g19_bridge_latency import run


def test_actual_bridge_latency_probe_records_two_internal_stages(tmp_path: Path) -> None:
    result = run(tmp_path / "result.json", tmp_path / "work", 20)
    latencies = result["latencies_ms"]

    assert result["source"] == "actual_bridge_capture_sender_no_network"
    assert result["production_real_orders"] == "DISABLED"
    assert len(latencies["event_enqueue_to_db"]) == 20
    assert len(latencies["event_enqueue_to_telegram"]) == 20
    assert all(value >= 0 for values in latencies.values() for value in values)


def test_bridge_latency_probe_rejects_too_few_iterations(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="at least 20"):
        run(tmp_path / "result.json", tmp_path / "work", 19)
