"""bot-ea core package."""

from .models import (
    AccountSnapshot,
    Bar,
    CapitalAllocation,
    CapitalAllocationMode,
    ExecutionGateResult,
    OperatingMode,
    PositionSizeRequest,
    PositionSizeResult,
    RiskPolicy,
    SymbolSnapshot,
    TradingStyle,
)
from .codex_cli_engine import CodexCLIEngine
from .mt5_adapter import MockMT5Adapter, MT5Adapter, OrderValidationResult, SymbolCapabilitySnapshot
from .mt5_snapshots import build_account_snapshot, build_symbol_snapshot
from .polling_runtime import AIIntent, DecisionAction, PollingConfig, PollingRuntime, PollingCycleResult, RuntimeSnapshot
from .risk_engine import RiskEngine
from .runtime_store import RuntimeStore
from .stop_policy import SessionPerformance, StopDecision, StopPolicy, StopReason, evaluate_stop_policy
from .validation import TradeRecord, ValidationSummary, evaluate_cost_realism, export_summary_markdown, summarize_trades

__all__ = [
    "AccountSnapshot",
    "AIIntent",
    "Bar",
    "CapitalAllocation",
    "CapitalAllocationMode",
    "CodexCLIEngine",
    "DecisionAction",
    "ExecutionGateResult",
    "MockMT5Adapter",
    "MT5Adapter",
    "OperatingMode",
    "OrderValidationResult",
    "PollingConfig",
    "PollingCycleResult",
    "PollingRuntime",
    "PositionSizeRequest",
    "PositionSizeResult",
    "RiskEngine",
    "RiskPolicy",
    "RuntimeSnapshot",
    "RuntimeStore",
    "SessionPerformance",
    "SymbolSnapshot",
    "SymbolCapabilitySnapshot",
    "StopDecision",
    "StopPolicy",
    "StopReason",
    "TradeRecord",
    "TradingStyle",
    "ValidationSummary",
    "build_account_snapshot",
    "build_symbol_snapshot",
    "evaluate_stop_policy",
    "evaluate_cost_realism",
    "export_summary_markdown",
    "summarize_trades",
]
