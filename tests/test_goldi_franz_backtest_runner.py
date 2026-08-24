from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts/run-goldi-franz-backtests.ps1"


def test_runner_is_tester_only_and_reproducible() -> None:
    value = RUNNER.read_text(encoding="utf-8")
    assert '"[Tester]"' in value
    assert '"Model=4"' in value
    assert '"ExecutionMode=100"' in value
    assert '"InpEnableTesterOrders=true"' in value
    assert "The exact Strategy Tester terminal is already running" in value
    assert "Result: 0 errors, 0 warnings" in value
    assert "Copied EX5 checksum mismatch" in value
    assert 'real_orders = "DISABLED"' in value
    assert "safe.directory=$RepoRoot" in value
    assert "$safeBatchId" in value


def test_runner_locks_windows_balances_and_attribution_variants() -> None:
    value = RUNNER.read_text(encoding="utf-8")
    for date in (
        "2025.01.01",
        "2026.01.01",
        "2025.11.01",
        "2026.02.15",
        "2026.06.01",
        "2026.08.25",
        "2026.08.04",
        "2026.08.20",
        "2020.01.01",
    ):
        assert date in value
    assert 'BalanceCsv = "30,50,100"' in value
    assert '"FULL"' in value
    assert '"PRICE_ONLY"' in value
    assert '"NO_STOCH"' in value
    assert '"NO_FIB_GATE"' in value
    assert "coverage_ok = [bool]$coverageStart" in value
    assert "real ticks begin from" in value
    assert "tick_integrity_ok" in value


def test_runner_calculates_required_acceptance_metrics() -> None:
    value = RUNNER.read_text(encoding="utf-8")
    for field in (
        "completed_setups",
        "total_r",
        "expectancy_r",
        "profit_factor",
        "maximum_drawdown_r",
        "duplicate_event_ids",
        "stop_out",
        "handgun",
        "sniper",
    ):
        assert field in value
