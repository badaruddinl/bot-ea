from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from itertools import pairwise
from math import ceil
from statistics import median
from typing import Any

REQUIRED_COMPONENTS = ("GOLDI", "GOLDM", "BRIDGE")
RESOURCE_FIELDS = ("rss_bytes", "private_bytes", "handle_count", "thread_count")
REQUIRED_LATENCIES = (
    "bar_close_to_detection",
    "detection_to_decision",
    "entry_ready_to_submit",
    "submit_to_broker_ack",
    "event_enqueue_to_db",
    "event_enqueue_to_telegram",
)


class StabilitySchemaError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SeriesTrend:
    samples: int
    first: float
    last: float
    minimum: float
    median: float
    maximum: float
    slope_per_hour: float
    window_medians: tuple[float, ...]
    observed_noise: float
    monotonic_leak: bool


@dataclass(frozen=True, slots=True)
class ComponentTrend:
    component_id: str
    resources: dict[str, SeriesTrend]
    heartbeat_first: int | None
    heartbeat_last: int | None
    heartbeat_advanced: bool


@dataclass(frozen=True, slots=True)
class LatencySummary:
    samples: int
    p50_ms: float
    p95_ms: float
    maximum_ms: float


@dataclass(frozen=True, slots=True)
class StabilityReport:
    schema_version: int
    gate: str
    status: str
    duration_seconds: float
    sample_count: int
    components: dict[str, ComponentTrend]
    storage_idle_growth: dict[str, int]
    latencies: dict[str, LatencySummary]
    violations: tuple[str, ...]
    production_real_orders: str

    def to_payload(self) -> dict[str, Any]:
        return asdict(self)


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StabilitySchemaError(f"{label} must be numeric")
    result = float(value)
    if result < 0:
        raise StabilitySchemaError(f"{label} must be nonnegative")
    return result


def _integer(value: Any, label: str) -> int:
    result = _number(value, label)
    if not result.is_integer():
        raise StabilitySchemaError(f"{label} must be an integer")
    return int(result)


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise StabilitySchemaError(f"{label} must be an ISO timestamp")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StabilitySchemaError(f"{label} must be an ISO timestamp") from exc


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _slope_per_hour(times: list[float], values: list[float]) -> float:
    mean_time = sum(times) / len(times)
    mean_value = sum(values) / len(values)
    denominator = sum((value - mean_time) ** 2 for value in times)
    if denominator == 0:
        return 0.0
    slope_per_second = (
        sum(
            (time - mean_time) * (value - mean_value)
            for time, value in zip(times, values, strict=True)
        )
        / denominator
    )
    return slope_per_second * 3600.0


def _windows(values: list[float], count: int = 4) -> tuple[list[float], ...]:
    width = max(1, ceil(len(values) / count))
    return tuple(values[index : index + width] for index in range(0, len(values), width))


def _trend(times: list[float], values: list[float]) -> SeriesTrend:
    warmup = min(len(values) - 2, max(1, len(values) // 5))
    stable_values = values[warmup:]
    stable_times = times[warmup:]
    windows = _windows(stable_values)
    medians = tuple(median(window) for window in windows)
    noise = max(
        (_percentile(window, 0.95) - _percentile(window, 0.05) for window in windows),
        default=0.0,
    )
    median_growth = len(medians) >= 3 and all(
        later > earlier for earlier, later in pairwise(medians)
    )
    net_growth = medians[-1] - medians[0]
    monotonic_leak = median_growth and net_growth > noise
    return SeriesTrend(
        samples=len(stable_values),
        first=stable_values[0],
        last=stable_values[-1],
        minimum=min(stable_values),
        median=median(stable_values),
        maximum=max(stable_values),
        slope_per_hour=_slope_per_hour(stable_times, stable_values),
        window_medians=medians,
        observed_noise=noise,
        monotonic_leak=monotonic_leak,
    )


def analyze_stability(payload: dict[str, Any]) -> StabilityReport:
    if payload.get("schema_version") != 1:
        raise StabilitySchemaError("unsupported schema_version")
    if payload.get("production_real_orders") != "DISABLED":
        raise StabilitySchemaError("production REAL authority is unsafe")
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list) or len(raw_samples) < 12:
        raise StabilitySchemaError("at least 12 samples are required")

    observed = [
        _timestamp(sample.get("observed_at_utc"), f"samples[{index}].observed_at_utc")
        for index, sample in enumerate(raw_samples)
        if isinstance(sample, dict)
    ]
    if len(observed) != len(raw_samples):
        raise StabilitySchemaError("each sample must be an object")
    if any(later <= earlier for earlier, later in pairwise(observed)):
        raise StabilitySchemaError("sample timestamps must be strictly increasing")
    origin = observed[0]
    times = [(value - origin).total_seconds() for value in observed]
    duration = times[-1]
    interval = _number(payload.get("interval_seconds"), "interval_seconds")
    if interval <= 0 or duration < interval * (len(raw_samples) - 1) * 0.8:
        raise StabilitySchemaError("sample duration is incomplete")

    violations: list[str] = []
    components: dict[str, ComponentTrend] = {}
    for component_id in REQUIRED_COMPONENTS:
        resources: dict[str, SeriesTrend] = {}
        heartbeat_values: list[int] = []
        for field in RESOURCE_FIELDS:
            values = []
            for index, sample in enumerate(raw_samples):
                raw_components = sample.get("components")
                if not isinstance(raw_components, dict):
                    raise StabilitySchemaError(f"samples[{index}].components must be an object")
                component = raw_components.get(component_id)
                if not isinstance(component, dict):
                    raise StabilitySchemaError(f"samples[{index}] missing component {component_id}")
                values.append(_number(component.get(field), f"{component_id}.{field}[{index}]"))
                if field == RESOURCE_FIELDS[0] and component_id != "BRIDGE":
                    heartbeat_values.append(
                        _integer(
                            component.get("heartbeat_generation"),
                            f"{component_id}.heartbeat_generation[{index}]",
                        )
                    )
            resources[field] = _trend(times, values)
            if resources[field].monotonic_leak:
                violations.append(f"{component_id} {field} has a monotonic leak trend")
        heartbeat_first: int | None
        heartbeat_last: int | None
        if heartbeat_values:
            heartbeat_first = heartbeat_values[0]
            heartbeat_last = heartbeat_values[-1]
            heartbeat_advanced = heartbeat_last > heartbeat_first
        else:
            heartbeat_first = heartbeat_last = None
            heartbeat_advanced = True
        if not heartbeat_advanced:
            violations.append(f"{component_id} heartbeat did not advance")
        components[component_id] = ComponentTrend(
            component_id,
            resources,
            heartbeat_first,
            heartbeat_last,
            heartbeat_advanced,
        )

    storage_names = ("database_bytes", "wal_bytes", "goldi_spool_bytes", "goldm_spool_bytes")
    storage_growth = {name: 0 for name in storage_names}
    previous_event_count: int | None = None
    previous_storage: dict[str, int] | None = None
    for index, sample in enumerate(raw_samples):
        storage = sample.get("storage")
        if not isinstance(storage, dict):
            raise StabilitySchemaError(f"samples[{index}].storage must be an object")
        event_count = _integer(storage.get("event_count"), f"event_count[{index}]")
        current = {name: _integer(storage.get(name), f"{name}[{index}]") for name in storage_names}
        if previous_storage is not None and event_count == previous_event_count:
            for name in storage_names:
                if current[name] > previous_storage[name]:
                    storage_growth[name] += 1
        previous_storage = current
        previous_event_count = event_count
    for name, count in storage_growth.items():
        if count:
            violations.append(f"{name} grew {count} times while event_count was idle")

    raw_latencies = payload.get("latencies_ms")
    if not isinstance(raw_latencies, dict):
        raise StabilitySchemaError("latencies_ms must be an object")
    latencies: dict[str, LatencySummary] = {}
    for name in REQUIRED_LATENCIES:
        raw_values = raw_latencies.get(name)
        if not isinstance(raw_values, list) or not raw_values:
            violations.append(f"latency stage {name} is missing")
            continue
        values = [_number(value, f"latencies_ms.{name}") for value in raw_values]
        latencies[name] = LatencySummary(
            len(values),
            _percentile(values, 0.50),
            _percentile(values, 0.95),
            max(values),
        )

    return StabilityReport(
        schema_version=1,
        gate="G19",
        status="PASS" if not violations else "FAIL",
        duration_seconds=duration,
        sample_count=len(raw_samples),
        components=components,
        storage_idle_growth=storage_growth,
        latencies=latencies,
        violations=tuple(violations),
        production_real_orders="DISABLED",
    )
