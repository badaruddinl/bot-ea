from __future__ import annotations

import ast
from pathlib import Path

import goldm_bear.replay as legacy_bear_replay
import goldm_revised.replay as legacy_revised_replay
from gold_portfolio import worker as legacy_portfolio_worker
from gold_engine_core.rules.bear import BearEngine, _ceil_to_tick
from gold_engine_core.rules.bear_multitimeframe import BearMultiTimeframeReplay
from gold_engine_core.rules.revised import RevisedEngine, _normalize
from goldm_bear.engine import BearEngine as LegacyBearEngine
from goldm_bear.multitimeframe import BearMultiTimeframeReplay as LegacyBearMultiTimeframeReplay
from goldm_revised.engine import RevisedEngine as LegacyRevisedEngine

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PURE_RULE_MODULES = (
    "bear.py",
    "bear_candidate.py",
    "bear_multitimeframe.py",
    "revised.py",
    "revised_setup.py",
)


def test_legacy_replay_and_live_imports_share_exact_pure_rule_objects() -> None:
    assert LegacyRevisedEngine is RevisedEngine
    assert legacy_revised_replay.RevisedEngine is RevisedEngine
    assert LegacyBearEngine is BearEngine
    assert legacy_bear_replay.BearEngine is BearEngine
    assert LegacyBearMultiTimeframeReplay is BearMultiTimeframeReplay
    assert legacy_portfolio_worker.RevisedEngine is RevisedEngine
    assert legacy_portfolio_worker.BearMultiTimeframeReplay is BearMultiTimeframeReplay


def test_pure_rule_modules_have_no_runtime_adapter_dependencies() -> None:
    root = REPOSITORY_ROOT / "src" / "gold_engine_core" / "rules"
    forbidden_roots = {
        "MetaTrader5",
        "goldm_bear",
        "goldm_revised",
        "goldm_signal",
        "requests",
        "sqlite3",
        "telegram",
    }
    forbidden_calls = {"order_send", "sleep", "getenv"}

    for filename in PURE_RULE_MODULES:
        source = (root / filename).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported_roots = {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        } | {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }

        assert imported_roots.isdisjoint(forbidden_roots)
        assert calls.isdisjoint(forbidden_calls)


def test_tick_rounding_remains_profile_tick_driven() -> None:
    assert _normalize(4400.006, 0.01) == 4400.01
    assert _normalize(4400.004, 0.01) == 4400.01
    assert _ceil_to_tick(4400.001, 0.01) == 4400.01
    assert _ceil_to_tick(4400.01, 0.01) == 4400.01


def test_legacy_modules_are_compatibility_exports_not_duplicate_rules() -> None:
    paths = (
        REPOSITORY_ROOT / "src" / "goldm_revised" / "engine.py",
        REPOSITORY_ROOT / "src" / "goldm_revised" / "setup.py",
        REPOSITORY_ROOT / "src" / "goldm_bear" / "engine.py",
        REPOSITORY_ROOT / "src" / "goldm_bear" / "candidate.py",
        REPOSITORY_ROOT / "src" / "goldm_bear" / "multitimeframe.py",
    )
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not any(isinstance(node, (ast.ClassDef, ast.FunctionDef)) for node in tree.body)
