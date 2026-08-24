from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from gold_engine_core.g19_stability import StabilitySchemaError, analyze_stability


def evidence() -> dict[str, object]:
    started = datetime(2026, 8, 21, tzinfo=UTC)
    samples = []
    for index in range(16):
        samples.append(
            {
                "observed_at_utc": (started + timedelta(seconds=index * 5)).isoformat(),
                "components": {
                    "GOLDI": {
                        "rss_bytes": 1000 + (index % 3),
                        "private_bytes": 800 + (index % 2),
                        "handle_count": 50 + (index % 2),
                        "thread_count": 12,
                        "heartbeat_generation": 100 + index,
                    },
                    "GOLDM": {
                        "rss_bytes": 1100 + (index % 2),
                        "private_bytes": 850 + (index % 3),
                        "handle_count": 55,
                        "thread_count": 13 + (index % 2),
                        "heartbeat_generation": 200 + index,
                    },
                    "BRIDGE": {
                        "rss_bytes": 500 + (index % 2),
                        "private_bytes": 400 + (index % 3),
                        "handle_count": 20,
                        "thread_count": 4,
                    },
                },
                "storage": {
                    "event_count": 12,
                    "database_bytes": 4096,
                    "wal_bytes": 0,
                    "goldi_spool_bytes": 1024,
                    "goldm_spool_bytes": 2048,
                },
            }
        )
    return {
        "schema_version": 1,
        "interval_seconds": 5,
        "samples": samples,
        "latencies_ms": {
            "bar_close_to_detection": [10.0, 12.0],
            "detection_to_decision": [2.0, 3.0],
            "entry_ready_to_submit": [4.0],
            "submit_to_broker_ack": [80.0],
            "event_enqueue_to_db": [5.0],
            "event_enqueue_to_telegram": [100.0],
        },
        "production_real_orders": "DISABLED",
    }


def test_stable_observed_baseline_passes_without_fixed_ram_limit() -> None:
    report = analyze_stability(evidence())

    assert report.status == "PASS"
    assert not report.violations
    assert report.components["GOLDI"].heartbeat_advanced is True
    assert report.storage_idle_growth["database_bytes"] == 0


def test_monotonic_post_warmup_resource_growth_fails() -> None:
    payload = evidence()
    for index, sample in enumerate(payload["samples"]):  # type: ignore[index]
        sample["components"]["GOLDM"]["private_bytes"] = 1000 + index * 100  # type: ignore[index]

    report = analyze_stability(payload)
    assert report.status == "FAIL"
    assert any("GOLDM private_bytes" in value for value in report.violations)


def test_idle_storage_growth_and_profile_starvation_fail() -> None:
    payload = evidence()
    for index, sample in enumerate(payload["samples"]):  # type: ignore[index]
        sample["storage"]["database_bytes"] = 4096 + index  # type: ignore[index]
        sample["components"]["GOLDI"]["heartbeat_generation"] = 1  # type: ignore[index]

    report = analyze_stability(payload)
    assert report.status == "FAIL"
    assert any("database_bytes grew" in value for value in report.violations)
    assert any("GOLDI heartbeat" in value for value in report.violations)


def test_missing_latency_stage_fails_closed() -> None:
    payload = evidence()
    del payload["latencies_ms"]["submit_to_broker_ack"]  # type: ignore[index]

    report = analyze_stability(payload)
    assert report.status == "FAIL"
    assert any("submit_to_broker_ack" in value for value in report.violations)


def test_schema_rejects_short_or_unsafe_capture() -> None:
    short = evidence()
    short["samples"] = short["samples"][:4]  # type: ignore[index]
    with pytest.raises(StabilitySchemaError, match="at least 12"):
        analyze_stability(short)

    unsafe = deepcopy(evidence())
    unsafe["production_real_orders"] = "ENABLED"
    with pytest.raises(StabilitySchemaError, match="unsafe"):
        analyze_stability(unsafe)
