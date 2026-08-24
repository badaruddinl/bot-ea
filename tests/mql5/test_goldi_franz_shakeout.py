import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXPERT = ROOT / "mt5/Experts/bot-ea/GoldIFranzShakeout.mq5"
HARNESS = ROOT / "mt5/Experts/bot-ea/GoldIFranzShakeoutHarness.mq5"
TYPES = ROOT / "mt5/Include/bot-ea/GoldIFranzTypes.mqh"
STRATEGY = ROOT / "mt5/Include/bot-ea/GoldIFranzStrategy.mqh"
PERSISTENCE = ROOT / "mt5/Include/bot-ea/GoldIFranzPersistence.mqh"
RUNTIME = ROOT / "mt5/Include/bot-ea/GoldIFranzRuntime.mqh"
AUDIT = ROOT / "mt5/Include/bot-ea/GoldIFranzAudit.mqh"
CONFIG = ROOT / "config/goldi_franz_shakeout.json"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_profile_is_standalone_tester_only_and_exactly_locked() -> None:
    expert = _read(EXPERT)
    strategy = _read(STRATEGY)
    runtime = _read(RUNTIME)
    combined = "\n".join(_read(path) for path in (EXPERT, TYPES, STRATEGY, RUNTIME))
    assert "#property strict" in expert
    assert '#define FRANZ_STRATEGY_ID "GOLDI_FRANZ_SHAKEOUT"' in strategy
    assert '#define FRANZ_SYMBOL "GOLD.i#"' in strategy
    assert "#define FRANZ_MAGIC 26081914" in strategy
    assert "TESTER_ONLY_EA" in runtime
    assert "MQLInfoInteger(MQL_TESTER)" in runtime
    assert "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING" in runtime
    assert "ACCOUNT_LEVERAGE)!=1000" in runtime
    assert "SYMBOL_TRADE_CONTRACT_SIZE)-100.0" in runtime
    for forbidden in (
        "GoldEngineRevised",
        "GoldEngineBear",
        "GoldMSniperParity",
        "GoldMHighRiskMicroScalper",
    ):
        assert forbidden not in combined


def test_config_fingerprint_matches_canonical_manifest() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    canonical = json.dumps(
        config, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode()
    expected = hashlib.sha256(canonical).hexdigest()
    match = re.search(r'FRANZ_PROFILE_FINGERPRINT "([0-9a-f]{64})"', _read(STRATEGY))
    assert match is not None
    assert match.group(1) == expected


def test_strategy_has_bounded_causal_multitimeframe_rules() -> None:
    strategy = _read(STRATEGY)
    runtime = _read(RUNTIME)
    assert "CopyRates(FRANZ_SYMBOL,timeframe,1,count" in runtime
    assert "PERIOD_D1" in runtime
    assert "PERIOD_H4" in runtime
    assert "PERIOD_H1" in runtime
    assert "PERIOD_M30" in runtime
    assert "PERIOD_M15" in runtime
    assert "PERIOD_M5" in runtime
    assert "PERIOD_M1" in runtime
    assert "FranzSwingDirection" in strategy
    assert "h1_efficiency<=0.35" in strategy
    assert "for(int length=3;length<=8;length++)" in strategy
    assert "body_share<0.65" in strategy
    assert "overlap_average>0.35" in strategy
    assert "CopyRates(FRANZ_SYMBOL,timeframe,0" not in runtime


def test_dual_trendline_zones_are_mandatory_before_initial_break_watch() -> None:
    types = _read(TYPES)
    strategy = _read(STRATEGY)
    runtime = _read(RUNTIME)
    assert "struct FranzTrendlineZone" in types
    assert "bull_zone" in types
    assert "bear_zone" in types
    assert "FranzBuildTrendlineZone" in strategy
    assert "touches>=2" in strategy
    assert "FranzInitialTrendlineBreak" in strategy
    assert "m_state.initial_trendline_break=true" in runtime
    assert "FranzInitialTrendlineBreak" in runtime
    assert "FranzTrendlineRetest" in runtime
    setup_block = runtime[
        runtime.index("bool CreateSetupFromM15") : runtime.index("bool BuildEntryDecision")
    ]
    assert "FranzBuildTrendlineZone(m15,true" in setup_block
    assert "FranzBuildTrendlineZone(m15,false" in setup_block


def test_swing_supply_demand_zones_require_base_departure_and_freshness() -> None:
    types = _read(TYPES)
    strategy = _read(STRATEGY)
    runtime = _read(RUNTIME)
    assert "struct FranzSwingZone" in types
    assert "FranzBuildSwingZone" in strategy
    assert "FranzFindSwingZone" in strategy
    assert "FranzMergeSwingZones" in strategy
    assert "FranzPriceInSwingZone" in strategy
    assert "FranzBody(bars[pivot_index])/pivot_range>0.55" in strategy
    assert "FranzBarOverlapRatio" in strategy
    assert "departure<1.5*median_range" in strategy
    assert "index<=240" in strategy
    assert "zone.invalidated=consecutive" in strategy
    assert "m_state.supply_zone=supply_zone" in runtime
    assert "m_state.demand_zone=demand_zone" in runtime
    assert "active_zone.distal" in runtime
    assert "FranzBarTouchesSwingZone" in runtime


def test_stochastic_only_reinforces_a_price_confirmed_failed_break() -> None:
    strategy = _read(STRATEGY)
    runtime = _read(RUNTIME)
    assert "FranzStochasticReinforced" in strategy
    assert "const int required_reentries=(stochastic_reinforced ? 1 : 2)" in strategy
    assert "reentry_closes>=required_reentries && micro_break" in strategy
    assert "accepted_outside=consecutive" in strategy
    assert "BREAK_ACCEPTED_OUTSIDE" in runtime
    assert "iStochastic(FRANZ_SYMBOL,PERIOD_M1,5,3,3,MODE_SMA,STO_LOWHIGH)" in runtime
    assert "FranzStochasticReinforced" not in _read(TYPES)


def test_rsi_and_fibonacci_are_mandatory_in_full_configuration() -> None:
    expert = _read(EXPERT)
    strategy = _read(STRATEGY)
    runtime = _read(RUNTIME)
    assert "InpUseRSI=true" in expert
    assert "InpUseFibonacciEntryGate=true" in expert
    assert "iRSI(FRANZ_SYMBOL,PERIOD_M1,7,PRICE_CLOSE)" in runtime
    assert "iRSI(FRANZ_SYMBOL,PERIOD_M5,14,PRICE_CLOSE)" in runtime
    assert "votes<2" in runtime
    assert "FranzComputeFibonacci" in strategy
    assert "0.236*range" in strategy
    assert "0.382*range" in strategy
    assert "0.618*range" in strategy
    assert "0.130*range" in strategy
    assert "0.146*fib.range" in strategy
    assert "FranzPassedHalfBeforeEntry" in runtime
    assert "m_state.fib_m1_bars>5" in runtime
    assert "m_state.setup_expires_at=tick.time+5*60" in runtime
    assert "FIBONACCI_ENTRY_EXPIRED" in runtime


def test_handgun_and_sniper_have_distinct_position_contracts() -> None:
    runtime = _read(RUNTIME)
    assert "decision.mode==FRANZ_MODE_SNIPER_TREND ? 2 : 1" in runtime
    assert "LegComment(1)" in runtime
    assert "LegComment(2)" in runtime
    assert "LEG2_SUBMIT_FAILED" in runtime
    assert "CloseTicket(m_state.leg1_ticket)" in runtime
    assert "ProtectSecondLeg" in runtime
    assert "m_state.planned_entry+0.10*risk" in runtime
    assert "m_state.fibonacci.level_1272" in runtime
    assert "MAXIMUM_HOLD_REACHED" in runtime


def test_fixed_lot_risk_and_daily_guards_are_explicit() -> None:
    runtime = _read(RUNTIME)
    assert "m_trade.Buy(0.01" in runtime
    assert "m_trade.Sell(0.01" in runtime
    assert "tick.ask-tick.bid>0.60" in runtime
    assert "0.10*equity" in runtime
    assert "equity-4.0" in runtime
    assert "m_state.daily_setups>=3" in runtime
    assert "m_state.daily_r<=-2.0 || m_state.daily_r>=3.0" in runtime
    assert "m_state.cooldown_until=server_time+3600" in runtime


def test_state_persistence_is_double_slot_fingerprinted_and_restart_aware() -> None:
    persistence = _read(PERSISTENCE)
    runtime = _read(RUNTIME)
    assert '"bot-ea\\\\goldi-franz\\\\"+m_namespace' in persistence
    assert 'BasePath()+"\\\\state-"' in persistence
    assert "state.generation%2" in persistence
    assert "FranzStateChecksum" in persistence
    assert "count!=89" in persistence
    assert "FRANZ_PROFILE_FINGERPRINT" in persistence
    assert "ReconcileRestart" in runtime
    assert "POSITION_COUNT_AMBIGUOUS" in runtime
    assert "POSITION_COMMENT_MISMATCH" in runtime


def test_manual_and_foreign_positions_are_not_selected_or_mutated() -> None:
    runtime = _read(RUNTIME)
    assert "PositionGetInteger(POSITION_MAGIC)!=FRANZ_MAGIC" in runtime
    assert "!OwnComment(PositionGetString(POSITION_COMMENT))" in runtime
    assert "CloseTicket" in runtime
    assert "m_trade.PositionClose(ticket,30)" in runtime


def test_audit_is_transition_only_and_tester_local() -> None:
    audit = _read(AUDIT)
    runtime = _read(RUNTIME)
    assert 'BasePath()+"\\\\audit.jsonl"' in audit
    assert "m_store.Configure(run_id)" in runtime
    assert "m_audit.Configure(run_id)" in runtime
    assert "FILE_COMMON" not in audit
    assert "m_audit.Emit" in runtime
    assert "Telegram" not in audit


def test_harness_is_non_trading_and_covers_core_symmetry() -> None:
    harness = _read(HARNESS)
    assert "orders_sent=0" in harness
    assert "authority=DISABLED" in harness
    assert "SELL_FIB_BUILD" in harness
    assert "BUY_FIB_BUILD" in harness
    assert "FAILED_BREAK_TWO_REENTRY" in harness
    assert "FAILED_BREAK_STOCH_REINFORCED" in harness
    assert "PERSIST_SAVE" in harness
