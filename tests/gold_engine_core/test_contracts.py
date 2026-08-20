from __future__ import annotations

import ast
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from gold_engine_core import (
    Bar,
    BarSeries,
    ContractError,
    DecisionAction,
    EngineEvent,
    EngineEventType,
    EngineOutput,
    MarketSnapshot,
    PositionState,
    PositionStatus,
    ProfileConfig,
    PureStrategyEngine,
    SetupState,
    Side,
    SignalPlan,
    StateField,
    StrategyConfig,
    StrategyDecision,
    StrategyKind,
    StrategyPhase,
    StrategyState,
    Tick,
    Timeframe,
    WarmupRequirement,
    load_named_profile,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TZ = timezone(timedelta(hours=3))
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=TZ)
D = Decimal


def bar(index: int = 0, *, close_time: datetime | None = None) -> Bar:
    start = NOW + timedelta(minutes=index)
    return Bar(
        open_time=start,
        close_time=close_time or start + timedelta(minutes=1),
        open=D("4400.00"),
        high=D("4401.00"),
        low=D("4399.00"),
        close=D("4400.50"),
        tick_volume=100,
        spread=D("0.20"),
    )


def tick(*, time: datetime = NOW + timedelta(minutes=2)) -> Tick:
    return Tick(time=time, bid=D("4400.00"), ask=D("4400.20"), volume=10.0)


def profile(profile_id: str = "GOLDI") -> ProfileConfig:
    return ProfileConfig.from_manifest(
        load_named_profile(REPOSITORY_ROOT, profile_id), tick_size=D("0.01")
    )


def strategy() -> StrategyConfig:
    return StrategyConfig(
        strategy_id="GOLDM_REVISED",
        strategy_version="0.6.0",
        kind=StrategyKind.REVISED,
        warmup=(
            WarmupRequirement(Timeframe.M1, 2),
            WarmupRequirement(Timeframe.M5, 2),
        ),
        maximum_history_bars=100,
    )


def state(*, sequence: int = 0, as_of: datetime = NOW) -> StrategyState:
    return StrategyState(
        profile_id="GOLDI",
        strategy_id="GOLDM_REVISED",
        strategy_version="0.6.0",
        phase=StrategyPhase.IDLE,
        as_of=as_of,
        sequence=sequence,
        warmup_complete=True,
    )


def signal() -> SignalPlan:
    return SignalPlan(
        profile_id="GOLDI",
        profile_version="1.0.0",
        strategy_id="GOLDM_REVISED",
        strategy_version="0.6.0",
        setup_id="GOLDI:setup:1",
        signal_id="GOLDI:signal:1",
        side=Side.BUY,
        symbol="GOLD.i#",
        setup_created_at=NOW,
        entry_ready_at=NOW + timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=3),
        planned_entry=D("4400.00"),
        stop=D("4390.00"),
        target=D("4425.00"),
        planned_risk=D("10.00"),
        invalidation=D("4390.00"),
        maximum_spread=D("0.40"),
        maximum_drift_r=D("0.20"),
        tick_size=D("0.01"),
        account_login=123456,
        account_server="XMGlobal-MT5 5",
        trade_mode="demo",
        terminal_identity="GOLDI_DEDICATED_TERMINAL",
        magic=26081911,
    )


@dataclass(frozen=True, slots=True)
class ProbeEngine:
    profile: ProfileConfig
    config: StrategyConfig

    def _next(self, previous: StrategyState, available_at: datetime) -> EngineOutput:
        next_state = replace(
            previous,
            as_of=max(previous.as_of, available_at),
            sequence=previous.sequence + 1,
        )
        output = EngineOutput(next_state)
        output.validate_after(previous)
        return output

    def on_warmup(self, history: MarketSnapshot) -> EngineOutput:
        self.profile.validate_market(profile_id=history.profile_id, symbol=history.symbol)
        for requirement in self.config.warmup:
            if len(history.bars(requirement.timeframe)) < requirement.bars:
                raise ContractError("insufficient bounded warmup")
        next_state = StrategyState(
            profile_id=self.profile.profile_id,
            strategy_id=self.config.strategy_id,
            strategy_version=self.config.strategy_version,
            phase=StrategyPhase.IDLE,
            as_of=history.available_at,
            sequence=0,
            warmup_complete=True,
        )
        event = EngineEvent(
            event_id="warmup:1",
            event_type=EngineEventType.WARMUP_COMPLETED,
            payload_version=1,
            available_at=history.available_at,
            profile_id=self.profile.profile_id,
            strategy_id=self.config.strategy_id,
            reason="BOUNDED_HISTORY_READY",
        )
        output = EngineOutput(next_state, events=(event,))
        output.validate_after(None)
        return output

    def on_bar_close(self, state: StrategyState, timeframe: Timeframe, bar: Bar) -> EngineOutput:
        del timeframe
        return self._next(state, bar.close_time)

    def on_tick(self, state: StrategyState, tick: Tick) -> EngineOutput:
        return self._next(state, tick.time)

    def on_position_event(self, state: StrategyState, event: EngineEvent) -> EngineOutput:
        return self._next(state, event.available_at)


def snapshot() -> MarketSnapshot:
    bars = (bar(0), bar(1))
    return MarketSnapshot(
        profile_id="GOLDI",
        symbol="GOLD.i#",
        available_at=bars[-1].close_time,
        series=(
            BarSeries(Timeframe.M1, bars),
            BarSeries(Timeframe.M5, bars),
        ),
    )


def test_pure_engine_uses_explicit_profile_and_all_required_interfaces() -> None:
    engine = ProbeEngine(profile(), strategy())
    assert isinstance(engine, PureStrategyEngine)

    warm = engine.on_warmup(snapshot())
    after_bar = engine.on_bar_close(warm.next_state, Timeframe.M1, bar(3))
    after_tick = engine.on_tick(after_bar.next_state, tick(time=NOW + timedelta(minutes=5)))
    event = EngineEvent(
        "position:1",
        EngineEventType.POSITION_UPDATED,
        1,
        NOW + timedelta(minutes=6),
        "GOLDI",
        "GOLDM_REVISED",
        "POSITION_SYNC",
    )
    after_position = engine.on_position_event(after_tick.next_state, event)

    assert warm.events[0].event_type is EngineEventType.WARMUP_COMPLETED
    assert after_position.next_state.sequence == 3


def test_core_contract_module_has_no_forbidden_runtime_dependency() -> None:
    path = REPOSITORY_ROOT / "src" / "gold_engine_core" / "contracts.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert imports.isdisjoint({"MetaTrader5", "os", "sqlite3", "requests", "telegram", "time"})
    for forbidden in ("order_send", "sleep(", "getenv", "environ"):
        assert forbidden not in source
    assert "GOLD.i" not in source
    assert "GOLDm" not in source


def test_market_snapshot_is_closed_bar_causal_and_profile_explicit() -> None:
    value = snapshot()
    assert value.bars(Timeframe.M1) == value.series[0].bars
    assert value.bars(Timeframe.H1) == ()
    profile().validate_market(profile_id=value.profile_id, symbol=value.symbol)
    with pytest.raises(ContractError, match="explicit profile"):
        profile().validate_market(profile_id="GOLDM", symbol="GOLDm#")


def test_bar_tick_and_series_reject_invalid_market_data() -> None:
    valid = bar()
    bad_bars = (
        lambda: replace(valid, close_time=valid.open_time),
        lambda: replace(valid, open=D("NaN")),
        lambda: replace(valid, spread=D("-0.01")),
        lambda: replace(valid, tick_volume=-1),
        lambda: replace(valid, high=D("4399.50")),
        lambda: replace(valid, low=D("4400.60")),
    )
    for mutation in bad_bars:
        with pytest.raises(ContractError):
            mutation()

    with pytest.raises(ContractError, match="ask"):
        Tick(NOW, D("4401"), D("4400"))
    with pytest.raises(ContractError, match="volume"):
        Tick(NOW, D("4400"), D("4401"), volume=float("inf"))
    with pytest.raises(ContractError, match="cannot be empty"):
        BarSeries(Timeframe.M1, ())
    with pytest.raises(ContractError, match="unique ascending"):
        BarSeries(Timeframe.M1, (valid, valid))


def test_snapshot_rejects_duplicate_and_future_market_inputs() -> None:
    series = BarSeries(Timeframe.M1, (bar(),))
    with pytest.raises(ContractError, match="duplicate"):
        MarketSnapshot("GOLDI", "GOLD.i#", NOW + timedelta(minutes=1), (series, series))
    with pytest.raises(ContractError, match="bar unavailable"):
        MarketSnapshot("GOLDI", "GOLD.i#", NOW, (series,))
    with pytest.raises(ContractError, match="future tick"):
        MarketSnapshot(
            "GOLDI",
            "GOLD.i#",
            NOW + timedelta(minutes=1),
            (series,),
            tick(time=NOW + timedelta(minutes=2)),
        )


def test_strategy_and_profile_configs_are_bounded_and_profile_locked() -> None:
    assert profile("GOLDI").symbol == "GOLD.i#"
    assert profile("GOLDM").symbol == "GOLDm#"
    with pytest.raises(ContractError, match="positive"):
        WarmupRequirement(Timeframe.M1, 0)
    with pytest.raises(ContractError, match="bounded warmup"):
        replace(strategy(), warmup=())
    with pytest.raises(ContractError, match="unique"):
        replace(
            strategy(),
            warmup=(WarmupRequirement(Timeframe.M1, 1), WarmupRequirement(Timeframe.M1, 2)),
        )
    with pytest.raises(ContractError, match="below"):
        replace(strategy(), maximum_history_bars=1)
    with pytest.raises(ContractError, match="bounded"):
        replace(strategy(), maximum_history_bars=100_001)
    with pytest.raises(ContractError, match="integer limits"):
        replace(profile(), magic=0)


def test_setup_state_and_strategy_state_are_causal_and_typed() -> None:
    setup = SetupState(
        "GOLDI:setup:1",
        Side.BUY,
        Timeframe.M5,
        "M1_CONFIRMATION",
        NOW,
        NOW + timedelta(minutes=12),
        D("4390"),
    )
    current = replace(
        state(as_of=NOW + timedelta(minutes=1)),
        phase=StrategyPhase.WATCH,
        setup=setup,
        fields=(StateField("touches", 2), StateField("level", D("4400"))),
    )
    assert current.setup == setup
    with pytest.raises(ContractError, match="after created"):
        replace(setup, valid_until=NOW)
    with pytest.raises(ContractError, match="unique names"):
        replace(current, fields=(StateField("x", 1), StateField("x", 2)))
    with pytest.raises(ContractError, match="future setup"):
        replace(current, as_of=NOW - timedelta(minutes=1))
    with pytest.raises(ContractError, match="finite"):
        StateField("bad", D("NaN"))


def test_signal_plan_is_owned_causal_tick_aligned_and_structural() -> None:
    plan = signal()
    assert plan.planned_risk == D("10.00")
    invalid = (
        (lambda: replace(plan, valid_until=plan.entry_ready_at), "timestamps"),
        (lambda: replace(plan, planned_risk=D("9")), "entry-stop"),
        (lambda: replace(plan, stop=D("4401"), planned_risk=D("1")), "BUY"),
        (
            lambda: replace(plan, planned_entry=D("4400.005"), planned_risk=D("10.005")),
            "tick_size",
        ),
        (lambda: replace(plan, account_login=0), "ownership"),
    )
    for mutation, message in invalid:
        with pytest.raises(ContractError, match=message):
            mutation()

    sell = replace(
        plan,
        side=Side.SELL,
        stop=D("4410"),
        target=D("4380"),
        planned_risk=D("10"),
        invalidation=D("4410"),
    )
    assert sell.target < sell.planned_entry < sell.stop


def test_decision_position_event_and_output_guards_fail_closed() -> None:
    plan = signal()
    decision = StrategyDecision(
        "decision:1",
        plan.entry_ready_at,
        DecisionAction.ENTRY_READY,
        "CONFIRMED",
        setup_id=plan.setup_id,
        side=plan.side,
        signal_plan=plan,
    )
    position = PositionState(
        "position:1",
        "GOLDI",
        "GOLDM_REVISED",
        plan.signal_id,
        plan.symbol,
        plan.magic,
        plan.side,
        D("0.01"),
        plan.entry_ready_at,
        plan.planned_entry,
        plan.stop,
        plan.target,
        PositionStatus.OPEN,
        plan.entry_ready_at,
    )
    event = EngineEvent(
        "event:1",
        EngineEventType.SIGNAL_READY,
        1,
        plan.entry_ready_at,
        "GOLDI",
        "GOLDM_REVISED",
        "CONFIRMED",
        setup_id=plan.setup_id,
        signal_id=plan.signal_id,
    )
    output = EngineOutput(state(sequence=1, as_of=plan.entry_ready_at), (decision,), (event,))
    output.validate_after(state())
    assert position.status is PositionStatus.OPEN

    with pytest.raises(ContractError, match="requires a SignalPlan"):
        StrategyDecision("d", NOW, DecisionAction.ENTRY_READY, "reason")
    with pytest.raises(ContractError, match="event time"):
        replace(position, last_event_at=NOW - timedelta(minutes=1))
    with pytest.raises(ContractError, match="payload_version"):
        replace(event, payload_version=0)
    with pytest.raises(ContractError, match="increment"):
        replace(output, next_state=state(sequence=2)).validate_after(state())
    with pytest.raises(ContractError, match="changed profile"):
        replace(output, next_state=replace(output.next_state, profile_id="GOLDM")).validate_after(
            state()
        )
    cross_plan = replace(plan, profile_id="GOLDM")
    cross_decision = replace(decision, signal_plan=cross_plan)
    with pytest.raises(ContractError, match="crossed profile"):
        replace(output, decisions=(cross_decision,)).validate_after(state())
    with pytest.raises(ContractError, match="event crossed"):
        replace(output, events=(replace(event, profile_id="GOLDM"),)).validate_after(state())


def test_probe_warmup_rejects_missing_required_history() -> None:
    engine = ProbeEngine(profile(), strategy())
    one_bar = BarSeries(Timeframe.M1, (bar(),))
    value = MarketSnapshot("GOLDI", "GOLD.i#", bar().close_time, (one_bar,))
    with pytest.raises(ContractError, match="insufficient"):
        engine.on_warmup(value)
