from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from gold_engine_core import load_named_profile
from gold_engine_core.rules import BearEngine, confluence_v1_config
from gold_engine_core.rules.bear import BearAction, BearBar

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ORACLE = REPOSITORY_ROOT / "corpus" / "bear_parity" / "m15_scanner_oracle.json"
CAPTURE_SCRIPT = REPOSITORY_ROOT / "scripts" / "capture_g13_m15_oracle.py"
FIXTURE_SCRIPT = REPOSITORY_ROOT / "scripts" / "build_g13_m15_harness_fixture.py"
FIXTURE = REPOSITORY_ROOT / "mt5" / "Experts" / "bot-ea" / "fixtures" / "G13BearM15Oracle.mqh"


def test_m15_oracle_is_hashed_causal_profile_bound_and_recomputable() -> None:
    raw = ORACLE.read_bytes()
    payload = json.loads(raw)
    checksum = ORACLE.with_suffix(".sha256").read_text(encoding="ascii").split()

    assert checksum == [hashlib.sha256(raw).hexdigest(), ORACLE.name]
    assert payload["schema_version"] == 1
    assert payload["source_bar_count"] == 50
    assert payload["signal_time"] == "2026-08-18T17:00:00+03:00"
    assert len(payload["vectors"]) == 2
    for vector in payload["vectors"]:
        profile_id = vector["profile_id"]
        manifest = load_named_profile(REPOSITORY_ROOT, profile_id)
        assert vector["profile_fingerprint"] == manifest.fingerprint
        assert vector["symbol"] == manifest.symbol
        assert vector["spread_normalization"] == "PROFILE_RESEARCH_FLOOR"
        bars = tuple(
            BearBar(
                time=datetime.fromisoformat(item["time"]),
                open=item["open"],
                high=item["high"],
                low=item["low"],
                close=item["close"],
                tick_volume=item["tick_volume"],
                spread=item["spread"],
            )
            for item in vector["bars"]
        )
        config = replace(
            confluence_v1_config(symbol=manifest.symbol),
            spread_floor=vector["bars"][-1]["spread"],
        )
        actual = BearEngine(config).evaluate(bars)
        assert actual.action is BearAction.SELL
        assert actual.time.isoformat() == payload["signal_time"]
        assert actual.reason == vector["expected"]["reason"]
        assert actual.entry == vector["expected"]["entry"]
        assert actual.stop == vector["expected"]["stop"]
        assert actual.take_profit == vector["expected"]["take_profit"]
        assert actual.confluence_votes == vector["expected"]["confluence_votes"]


def test_capture_script_is_strictly_read_only() -> None:
    value = CAPTURE_SCRIPT.read_text(encoding="utf-8")

    assert "copy_rates_range" in value
    assert "account_info" in value
    assert "symbol_info" in value
    for forbidden in (
        "order_send",
        "order_check",
        "positions_get",
        "history_deals_get",
        "CTrade",
        "OrderSend",
    ):
        assert forbidden not in value


def test_mql5_fixture_generator_is_deterministic_and_matches_repository(tmp_path: Path) -> None:
    output = tmp_path / "G13BearM15Oracle.mqh"
    command = [sys.executable, str(FIXTURE_SCRIPT), "--output", str(output)]

    first = subprocess.run(command, check=True, capture_output=True, text=True)
    first_raw = output.read_bytes()
    second = subprocess.run(command, check=True, capture_output=True, text=True)

    assert first.stdout == second.stdout
    assert output.read_bytes() == first_raw == FIXTURE.read_bytes()
    value = first_raw.decode("utf-8")
    assert "ArrayResize(bars,50)" in value
    assert "D'2026.08.18 17:00:00'" in value
