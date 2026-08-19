from __future__ import annotations

import pytest

from goldm_revised.risk import AdaptiveCompoundSizer, AdaptiveRiskConfig


def test_sizer_floors_to_broker_step_without_rounding_up() -> None:
    decision = AdaptiveCompoundSizer(
        AdaptiveRiskConfig(risk_fraction=0.035)
    ).size(
        equity=100.0,
        high_water_equity=100.0,
        loss_per_lot=200.0,
        margin_per_lot=50.0,
    )

    assert decision.raw_risk_volume == pytest.approx(0.0175)
    assert decision.volume == 0.01
    assert decision.projected_loss == 2.0
    assert decision.projected_risk_fraction == pytest.approx(0.02)


def test_sizer_skips_when_risk_budget_cannot_fund_minimum_lot() -> None:
    decision = AdaptiveCompoundSizer(
        AdaptiveRiskConfig(risk_fraction=0.02)
    ).size(
        equity=50.0,
        high_water_equity=50.0,
        loss_per_lot=250.0,
        margin_per_lot=40.0,
    )

    assert decision.executable is False
    assert decision.volume == 0.0
    assert decision.reason == "BELOW_MINIMUM_EXECUTABLE_VOLUME"


def test_sizer_can_bridge_minimum_lot_without_exceeding_explicit_cap() -> None:
    decision = AdaptiveCompoundSizer(
        AdaptiveRiskConfig(
            risk_fraction=0.02,
            minimum_lot_risk_cap_fraction=0.05,
        )
    ).size(
        equity=100.0,
        high_water_equity=100.0,
        loss_per_lot=400.0,
        margin_per_lot=40.0,
    )

    assert decision.executable is True
    assert decision.volume == 0.01
    assert decision.reason == "MINIMUM_LOT_BRIDGE"
    assert decision.projected_risk_fraction == pytest.approx(0.04)


def test_sizer_rejects_bridge_when_minimum_lot_exceeds_cap() -> None:
    decision = AdaptiveCompoundSizer(
        AdaptiveRiskConfig(
            risk_fraction=0.02,
            minimum_lot_risk_cap_fraction=0.05,
        )
    ).size(
        equity=50.0,
        high_water_equity=50.0,
        loss_per_lot=400.0,
        margin_per_lot=40.0,
    )

    assert decision.executable is False
    assert decision.reason == "BELOW_MINIMUM_EXECUTABLE_VOLUME"


def test_sizer_decompounds_at_soft_and_medium_drawdown() -> None:
    config = AdaptiveRiskConfig(risk_fraction=0.04)
    sizer = AdaptiveCompoundSizer(config)

    soft = sizer.size(
        equity=89.0,
        high_water_equity=100.0,
        loss_per_lot=100.0,
        margin_per_lot=10.0,
    )
    medium = sizer.size(
        equity=84.0,
        high_water_equity=100.0,
        loss_per_lot=100.0,
        margin_per_lot=10.0,
    )

    assert soft.effective_risk_fraction == pytest.approx(0.03)
    assert medium.effective_risk_fraction == pytest.approx(0.02)


def test_sizer_pauses_at_hard_drawdown() -> None:
    decision = AdaptiveCompoundSizer().size(
        equity=75.0,
        high_water_equity=100.0,
        loss_per_lot=100.0,
        margin_per_lot=10.0,
    )

    assert decision.executable is False
    assert decision.reason == "HARD_DRAWDOWN_PAUSE"
    assert decision.effective_risk_fraction == 0.0


def test_sizer_applies_margin_cap_before_step_floor() -> None:
    decision = AdaptiveCompoundSizer(
        AdaptiveRiskConfig(risk_fraction=0.10, maximum_margin_fraction=0.20)
    ).size(
        equity=100.0,
        high_water_equity=100.0,
        loss_per_lot=10.0,
        margin_per_lot=200.0,
    )

    assert decision.raw_risk_volume == pytest.approx(1.0)
    assert decision.raw_margin_volume == pytest.approx(0.1)
    assert decision.volume == 0.1
    assert decision.projected_margin == pytest.approx(20.0)
