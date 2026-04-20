"""bot-ea core package."""

from .models import (
    AccountSnapshot,
    Bar,
    ExecutionGateResult,
    OperatingMode,
    PositionSizeRequest,
    PositionSizeResult,
    RiskPolicy,
    SymbolSnapshot,
    TradingStyle,
)
from .mt5_adapter import MockMT5Adapter, MT5Adapter, OrderValidationResult, SymbolCapabilitySnapshot
from .mt5_snapshots import build_account_snapshot, build_symbol_snapshot
from .risk_engine import RiskEngine
from .validation import TradeRecord, ValidationSummary, evaluate_cost_realism, export_summary_markdown, summarize_trades

__all__ = [
    "AccountSnapshot",
    "Bar",
    "ExecutionGateResult",
    "MockMT5Adapter",
    "MT5Adapter",
    "OperatingMode",
    "OrderValidationResult",
    "PositionSizeRequest",
    "PositionSizeResult",
    "RiskEngine",
    "RiskPolicy",
    "SymbolSnapshot",
    "SymbolCapabilitySnapshot",
    "TradeRecord",
    "TradingStyle",
    "ValidationSummary",
    "build_account_snapshot",
    "build_symbol_snapshot",
    "evaluate_cost_realism",
    "export_summary_markdown",
    "summarize_trades",
]
