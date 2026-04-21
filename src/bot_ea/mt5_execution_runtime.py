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
        if intent.action not in {
            DecisionAction.OPEN,
            DecisionAction.ADD,
            DecisionAction.REDUCE,
            DecisionAction.CLOSE,
            DecisionAction.CANCEL_PENDING,
        }:
            return self._reject(f"unsupported action {intent.action.value}")
        if intent.action is not DecisionAction.CANCEL_PENDING and intent.side not in {"buy", "sell"}:
            return self._reject("intent side must be buy or sell")
        if intent.action is not DecisionAction.CANCEL_PENDING and size_result.normalized_volume <= 0:
            return self._reject("normalized volume must be positive")

        preflight = preflight_result or self.preflight(snapshot, intent, size_result)
        if preflight["status"] != "PRECHECK_OK":
            return preflight
        if not self.allow_live_orders:
            preflight["status"] = "DRY_RUN_OK"
            preflight["detail"] = f"dry-run only: {preflight['detail']}"
            preflight["quoted_price"] = float(preflight["request"].get("price") or 0.0)
            preflight["realized_price"] = None
            preflight["slippage_points"] = 0.0
            preflight["fill_latency_ms"] = 0.0
            preflight["commission_cash"] = None
            preflight["swap_cash"] = None
            return preflight

        live_request = self._refresh_live_request(snapshot, preflight["request"])
        live_validation = self.adapter.validate_order(live_request)
        if not live_validation.accepted:
            return {
                "status": "PRECHECK_REJECTED",
                "detail": live_validation.detail,
                "retcode": str(live_validation.retcode or ""),
                "projected_margin_free": live_validation.projected_margin_free,
                "projected_margin_level": live_validation.projected_margin_level,
                "guard_checks": preflight["guard_checks"],
                "request": live_request,
                "live_order_submitted": False,
                "preflight_status": "PRECHECK_REJECTED",
                "preflight_detail": live_validation.detail,
            }

        started = perf_counter()
        send_result = self.adapter.send_order(live_request)
        latency_ms = (perf_counter() - started) * 1000.0
        quoted_price = float(live_request.get("price") or 0.0)
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
            "request": live_request,
            "guard_checks": preflight["guard_checks"],
            "quoted_price": quoted_price,
            "realized_price": realized_price,
            "slippage_points": slippage_points,
            "fill_latency_ms": latency_ms,
            "commission_cash": None,
            "swap_cash": None,
        }

    def preflight(self, snapshot, intent, size_result) -> dict:
        if intent.action is DecisionAction.CANCEL_PENDING:
            request = self._build_order_request(snapshot, intent, size_result, 0.0)
            validation = self.adapter.validate_order(request)
            return {
                "status": "PRECHECK_OK" if validation.accepted else "PRECHECK_REJECTED",
                "detail": validation.detail,
                "retcode": str(validation.retcode or ""),
                "projected_margin_free": validation.projected_margin_free,
                "projected_margin_level": validation.projected_margin_level,
                "guard_checks": [],
                "request": request,
                "live_order_submitted": False,
                "preflight_status": "PRECHECK_OK" if validation.accepted else "PRECHECK_REJECTED",
                "preflight_detail": validation.detail,
            }
        if intent.side not in {"buy", "sell"}:
            return self._reject("intent side must be buy or sell")
        stop_distance_points = float(intent.stop_distance_points or snapshot.stop_distance_points)
        if intent.action in {DecisionAction.CLOSE, DecisionAction.REDUCE}:
            request = self._build_order_request(snapshot, intent, size_result, stop_distance_points)
            validation = self.adapter.validate_order(request)
            return {
                "status": "PRECHECK_OK" if validation.accepted else "PRECHECK_REJECTED",
                "detail": validation.detail,
                "retcode": str(validation.retcode or ""),
                "projected_margin_free": validation.projected_margin_free,
                "projected_margin_level": validation.projected_margin_level,
                "guard_checks": [],
                "request": request,
                "live_order_submitted": False,
                "preflight_status": "PRECHECK_OK" if validation.accepted else "PRECHECK_REJECTED",
                "preflight_detail": validation.detail,
            }
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
        request = {
            "symbol": snapshot.symbol,
            "action": intent.action.value.lower(),
            "deviation": self.deviation_points,
            "magic": self.magic,
            "comment": f"{self.comment_prefix}: {(intent.reason or 'execution')[:24]}",
        }
        if intent.action is DecisionAction.CANCEL_PENDING:
            request["order_ticket"] = (
                intent.payload.get("order_ticket")
                or intent.payload.get("pending_order_ticket")
                or intent.payload.get("order")
            )
            return request

        request["volume"] = float(
            intent.payload.get("volume")
            or intent.payload.get("position_volume")
            or size_result.normalized_volume
            or 0.0
        )
        if intent.action in {DecisionAction.CLOSE, DecisionAction.REDUCE}:
            close_side = "sell" if side == "buy" else "buy"
            request["order_type"] = close_side
            request["position_ticket"] = (
                intent.payload.get("position_ticket")
                or intent.payload.get("broker_position_id")
                or intent.payload.get("position")
            )
            request["price"] = float(snapshot.ask if close_side == "buy" else snapshot.bid or 0.0)
            return request

        request["order_type"] = side
        request["price"] = float(intent.entry_price or (snapshot.ask if side == "buy" else snapshot.bid) or 0.0)
        request["stop_distance_points"] = stop_distance_points
        return request

    def _refresh_live_request(self, snapshot, request: dict) -> dict:
        refreshed = dict(request)
        if str(refreshed.get("action") or "").lower() == DecisionAction.CANCEL_PENDING.value.lower():
            return refreshed
        side = str(refreshed.get("order_type") or "buy")
        tick = self.adapter.load_price_tick(snapshot.symbol)
        refreshed_price = float(tick.ask if side == "buy" else tick.bid or 0.0)
        if refreshed_price > 0:
            refreshed["price"] = refreshed_price
        return refreshed

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
