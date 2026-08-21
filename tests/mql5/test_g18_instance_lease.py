from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEASE = ROOT / "mt5/Include/bot-ea/GoldEngineInstanceLease.mqh"
RUNTIME = ROOT / "mt5/Include/bot-ea/GoldEngineRuntime.mqh"
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldEngineInstanceLeaseHarness.mq5"


def test_lease_is_exclusive_profile_account_magic_and_cross_terminal() -> None:
    source = LEASE.read_text(encoding="utf-8")

    assert "profile.profile_id" in source
    assert "account_login" in source
    assert "profile.magic" in source
    assert "FILE_COMMON" in source
    assert "FILE_SHARE_READ" not in source
    assert "FILE_SHARE_WRITE" not in source
    assert 'reason="DUPLICATE_EA_INSTANCE"' in source
    assert "FileClose(m_handle)" in source


def test_runtime_acquires_before_warmup_and_releases_on_deinit() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert source.index("m_instance_lease.Acquire") < source.index("if(!Warmup())")
    assert "m_instance_lease.Release()" in source


def test_native_harness_proves_duplicate_refusal_and_recovery() -> None:
    source = HARNESS.read_text(encoding="utf-8")

    assert "duplicate_refused" in source
    assert "DUPLICATE_EA_INSTANCE" in source
    assert "first.Release()" in source
    assert "recovery_acquired" in source
    assert "other_profile_alive" in source
    assert "other_remained_alive" in source
    assert "one_profile_restart=" in source
    assert "cross_terminal=FILE_COMMON_EXCLUSIVE" in source
    assert "order_authority=DISABLED" in source
