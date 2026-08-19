from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from goldm_revised.engine import RevisedBar


TZ = timezone(timedelta(hours=3))
SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "replay-goldm-revised-wide-stop.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("goldm_revised_execution_overlay", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_overlay(tmp_path: Path, monkeypatch, bars: list[RevisedBar], *extra: str):
    module = _load_script()

    class FakeInfo:
        point = 0.01

    class FakeMt5:
        TIMEFRAME_M1 = 1

        @staticmethod
        def symbol_info(_symbol: str):
            return FakeInfo()

        @staticmethod
        def last_error():
            return (1, "Success")

    class FakeLoader:
        def connect(self) -> None:
            pass

        def close(self) -> None:
            pass

        @staticmethod
        def _module():
            return FakeMt5()

        @staticmethod
        def _rates(*_args, **_kwargs):
            return bars

    report_path = tmp_path / "baseline.json"
    output_path = tmp_path / "overlay.json"
    report_path.write_text(
        json.dumps(
            {
                "from_time": datetime(2026, 1, 1, tzinfo=TZ).isoformat(),
                "to_time": datetime(2026, 1, 2, tzinfo=TZ).isoformat(),
                "outcomes": [
                    {
                        "opened_at": datetime(2026, 1, 1, 1, tzinfo=TZ).isoformat(),
                        "closed_at": datetime(2026, 1, 1, 2, tzinfo=TZ).isoformat(),
                        "entry": 100.0,
                        "stop": 98.0,
                        "target": 102.0,
                        "first_obstacle_r": 3.0,
                        "result": "TARGET",
                        "outcome_r": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(module, "RevisedMt5HistoryLoader", FakeLoader)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--report",
            str(report_path),
            "--output",
            str(output_path),
            "--stop-multiplier",
            "1.5",
            "--target-multiplier",
            "2.5",
            "--partial-fraction",
            "0.5",
            "--partial-target-multiplier",
            "1.0",
            *extra,
        ],
    )
    assert module.main() == 0
    return json.loads(output_path.read_text(encoding="utf-8"))


def _bar(minute: int, *, high: float, low: float, close: float = 100.0) -> RevisedBar:
    return RevisedBar(
        time=datetime(2026, 1, 1, 1, minute, tzinfo=TZ),
        open=100.0,
        high=high,
        low=low,
        close=close,
        volume=100.0,
        spread=0.2,
    )


def test_partial_then_runner_blends_realized_r(tmp_path: Path, monkeypatch) -> None:
    report = _run_overlay(
        tmp_path,
        monkeypatch,
        [_bar(0, high=102.1, low=99.0), _bar(1, high=105.1, low=99.0)],
    )

    outcome = report["outcomes"][0]
    assert outcome["result"] == "TARGET"
    assert outcome["partial_taken"] is True
    assert outcome["outcome_r"] == pytest.approx(7.0 / 6.0)
    assert outcome["target"] == pytest.approx(105.0)
    assert outcome["partial_target"] == pytest.approx(102.0)


def test_partial_then_stop_keeps_partial_profit(tmp_path: Path, monkeypatch) -> None:
    report = _run_overlay(
        tmp_path,
        monkeypatch,
        [_bar(0, high=102.1, low=99.0), _bar(1, high=101.0, low=96.9)],
    )

    outcome = report["outcomes"][0]
    assert outcome["result"] == "PARTIAL_STOP"
    assert outcome["outcome_r"] == pytest.approx(-1.0 / 6.0)
    assert report["partial_stop_count"] == 1


def test_same_bar_partial_and_stop_is_conservative_loss(
    tmp_path: Path, monkeypatch
) -> None:
    report = _run_overlay(
        tmp_path,
        monkeypatch,
        [_bar(0, high=102.1, low=96.9)],
    )

    outcome = report["outcomes"][0]
    assert outcome["result"] == "AMBIGUOUS_SAME_BAR"
    assert outcome["outcome_r"] == -1.0
    assert outcome["partial_taken"] is False


def test_invalid_buy_target_is_rejected(tmp_path: Path, monkeypatch) -> None:
    module = _load_script()
    # Exercise the CLI validation separately: a partial at/after its runner is invalid.
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--report",
            str(tmp_path / "unused.json"),
            "--output",
            str(tmp_path / "unused-output.json"),
            "--stop-multiplier",
            "1.5",
            "--target-multiplier",
            "1.0",
            "--partial-fraction",
            "0.5",
            "--partial-target-multiplier",
            "1.0",
        ],
    )
    with pytest.raises(ValueError, match="partial target must be before"):
        module.main()
