from __future__ import annotations

from dataclasses import asdict
from time import perf_counter

from .execution_guard import evaluate_execution_guards
from .polling_runtime import DecisionAction


class MT5ExecutionRuntime:
    """Live broker execution with safe-default dry-run behavior."""

    def __init__(
        self,
        *,
        adapter,
        allow_live_orders: bool = False,
        deviation_points: int = 20,
        magic: int = 234000,
        comment_prefix: str = "bot-ea",
    ) -> None:
        self.adapter = adapter
        self.allow_live_orders = allow_live_orders
        self.deviation_points = deviation_points
        self.magic = magic
        self.comment_prefix = comment_prefix

    def execute(self, snapshot, intent, size_result, preflight_result: dict | None = None) -> dict:
        if intent.action is not DecisionAction.OPEN:
            return self._reject(f"unsupported action {intent.action.value}")
        if intent.side not in {"buy", "sell"}:
            return self._reject("intent side must be buy or sell")
        if size_result.normalized_volume <= 0:
            return self._reject("normalized volume must be positive")

        preflight = preflight_result or self.preflight(snapshot, intent, size_result)
        if preflight["status"] != "PRECHECK_OK":
            return preflight
        if not self.allow_live_orders:
            preflight["status"] = "DRY_RUN_OK"
            preflight["detail"] = f"dry-run only: {preflight['detail']}"
            preflight["quoted_price"] = preflight["request"]["price"]
            preflight["realized_price"] = None
            preflight["slippage_points"] = 0.0
            preflight["fill_latency_ms"] = 0.0
            preflight["commission_cash"] = None
            preflight["swap_cash"] = None
            return preflight

        started = perf_counter()
        send_result = self.adapter.send_order(preflight["request"])
        latency_ms = (perf_counter() - started) * 1000.0
        quoted_price = float(preflight["request"]["price"] or 0.0)
        realized_price = float(send_result.price or quoted_price or 0.0)
        point = float(snapshot.symbol_snapshot.point or 0.0)
        slippage_points = abs(realized_price - quoted_price) / point if point > 0 and quoted_price > 0 else 0.0
        return {
            "status": "FILLED" if send_result.accepted else "REJECTED",
            "detail": send_result.detail,
            "retcode": str(send_result.retcode or ""),
            "order": send_result.order,
            "deal": send_result.deal,
            "volume": send_result.volume,
            "price": send_result.price,
            "bid": send_result.bid,
            "ask": send_result.ask,
            "request_id": send_result.request_id,
            "retcode_external": send_result.retcode_external,
            "live_order_submitted": True,
            "request": preflight["request"],
            "guard_checks": preflight["guard_checks"],
            "quoted_price": quoted_price,
            "realized_price": realized_price,
            "slippage_points": slippage_points,
            "fill_latency_ms": latency_ms,
            "commission_cash": None,
            "swap_cash": None,
        }

    def preflight(self, snapshot, intent, size_result) -> dict:
        if intent.side not in {"buy", "sell"}:
            return self._reject("intent side must be buy or sell")
        stop_distance_points = float(intent.stop_distance_points or snapshot.stop_distance_points)
        guard_result = evaluate_execution_guards(
            snapshot.account,
            snapshot.symbol_snapshot,
            snapshot.risk_policy,
            size_result.mode,
            stop_distance_points,
        )
        if not guard_result.allowed:
            return {
                "status": "GUARD_REJECTED",
                "detail": self._first_failed_check(guard_result),
                "retcode": "",
                "guard_checks": [asdict(check) for check in guard_result.checks],
                "live_order_submitted": False,
            }

        request = self._build_order_request(snapshot, intent, size_result, stop_distance_points)
        validation = self.adapter.validate_order(request)
        return {
            "status": "PRECHECK_OK" if validation.accepted else "PRECHECK_REJECTED",
            "detail": validation.detail,
            "retcode": str(validation.retcode or ""),
            "projected_margin_free": validation.projected_margin_free,
            "projected_margin_level": validation.projected_margin_level,
            "guard_checks": [asdict(check) for check in guard_result.checks],
            "request": request,
            "live_order_submitted": False,
            "preflight_status": "PRECHECK_OK" if validation.accepted else "PRECHECK_REJECTED",
            "preflight_detail": validation.detail,
        }

    def _build_order_request(self, snapshot, intent, size_result, stop_distance_points: float) -> dict:
        side = intent.side or "buy"
        return {
            "symbol": snapshot.symbol,
            "volume": size_result.normalized_volume,
            "order_type": side,
            "price": float(intent.entry_price or (snapshot.ask if side == "buy" else snapshot.bid) or 0.0),
            "stop_distance_points": stop_distance_points,
            "deviation": self.deviation_points,
            "magic": self.magic,
            "comment": f"{self.comment_prefix}: {(intent.reason or 'execution')[:24]}",
        }

    @staticmethod
    def _first_failed_check(guard_result) -> str:
        for check in guard_result.checks:
            if not check.passed:
                return check.detail
        return "execution guard rejected"

    @staticmethod
    def _reject(detail: str) -> dict:
        return {
            "status": "REJECTED",
            "detail": detail,
            "retcode": "",
            "live_order_submitted": False,
        }
