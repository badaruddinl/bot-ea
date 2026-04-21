from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timezone
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import websockets

from .desktop_runtime import DesktopRuntimeConfig, DesktopRuntimeCoordinator
from .models import CapitalAllocation, CapitalAllocationMode, OperatingMode, PositionSizeRequest, RiskPolicy, TradingStyle
from .mt5_adapter import LiveMT5Adapter
from .operator_state import AccountFingerprint, OperatorRuntimeSettings, OperatorStateStore
from .mt5_execution_runtime import MT5ExecutionRuntime
from .polling_runtime import AIIntent, DecisionAction, MT5SnapshotProvider
from .risk_engine import RiskEngine
from .runtime_store import RuntimeStore
from .validation import build_runtime_validation_report


class BotEaWebSocketService:
    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 8765,
        adapter_factory=LiveMT5Adapter,
        runtime_coordinator: DesktopRuntimeCoordinator | None = None,
        risk_engine: RiskEngine | None = None,
        risk_policy: RiskPolicy | None = None,
        project_root: str | Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.adapter_factory = adapter_factory
        self.risk_engine = risk_engine or RiskEngine()
        self.risk_policy = risk_policy or RiskPolicy(
            base_risk_pct=1.0,
            max_total_open_risk_pct=2.0,
            daily_loss_limit_pct=3.0,
        )
        self.runtime_coordinator = runtime_coordinator or DesktopRuntimeCoordinator(
            adapter_factory=adapter_factory,
            risk_policy=self.risk_policy,
        )
        self.state_store = OperatorStateStore(project_root or Path.cwd())
        self._clients: set[Any] = set()
        self._server = None
        self._drain_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._server = await websockets.serve(self._handle_client, self.host, self.port)
        self._drain_task = asyncio.create_task(self._drain_runtime_events())

    async def stop(self) -> None:
        if self._drain_task is not None:
            self._drain_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._drain_task
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle_client(self, websocket) -> None:
        self._clients.add(websocket)
        try:
            await websocket.send(json.dumps({"type": "event", "name": "service_ready", "payload": {"host": self.host, "port": self.port}}))
            async for raw_message in websocket:
                try:
                    request = json.loads(raw_message)
                    response = await self._handle_command(request)
                except Exception as exc:
                    response = {
                        "type": "response",
                        "id": request.get("id") if isinstance(request, dict) else None,
                        "ok": False,
                        "error": str(exc),
                    }
                await websocket.send(json.dumps(response, default=str))
        finally:
            self._clients.discard(websocket)

    async def _handle_command(self, request: dict[str, Any]) -> dict[str, Any]:
        request_id = request.get("id")
        name = str(request.get("name") or "")
        params = request.get("params") or {}
        if name == "probe_service_ready":
            result = {"host": self.host, "port": self.port, "detail": "Service lokal siap digunakan."}
        elif name == "load_runtime_settings":
            result = self.state_store.load_runtime_settings().to_dict()
        elif name == "save_runtime_settings":
            result = self.state_store.save_runtime_settings(self._settings_from_params(params))
        elif name == "load_runtime_state":
            result = await asyncio.to_thread(self._load_runtime_state, params)
        elif name == "probe_mt5_process":
            result = await asyncio.to_thread(self.runtime_coordinator.probe_mt5_process)
        elif name == "probe_mt5_session":
            result = await asyncio.to_thread(self.runtime_coordinator.probe_mt5_session)
        elif name == "probe_account_fingerprint":
            result = await asyncio.to_thread(self.runtime_coordinator.probe_account_fingerprint)
        elif name == "probe_symbol_baseline":
            self._require_runtime_idle(name)
            result = await asyncio.to_thread(self.runtime_coordinator.probe_symbol_baseline, **self._probe_kwargs(params))
        elif name == "probe_mt5":
            self._require_runtime_idle(name)
            result = await asyncio.to_thread(self.runtime_coordinator.probe_mt5, **self._probe_kwargs(params))
        elif name in {"probe_codex", "probe_ai_runtime"}:
            runtime_ready = await asyncio.to_thread(
                self.state_store.validate_runtime_command,
                command=str(params.get("codex_command") or params.get("ai_runtime_command") or "codex"),
                executable_path=str(params.get("ai_runtime_executable_path") or ""),
            )
            result = await asyncio.to_thread(self.runtime_coordinator.probe_codex, **self._codex_kwargs(params))
            if isinstance(result, str):
                result = {
                    "version": result,
                    "detail": f"AI runtime siap: {result}",
                    **runtime_ready,
                }
        elif name == "probe_ai_workspace":
            result = await asyncio.to_thread(
                self.state_store.validate_path,
                path=str(params["ai_workspace_path"]),
                label="Workspace AI",
                create=True,
                writable=True,
            )
        elif name == "probe_ai_documents":
            result = await asyncio.to_thread(
                self.state_store.validate_path,
                path=str(params["ai_documents_path"]),
                label="Dokumen AI",
                create=True,
                writable=False,
            )
        elif name == "probe_ai_context_store":
            result = await asyncio.to_thread(
                self.state_store.validate_path,
                path=str(params["ai_context_root"]),
                label="Folder context AI",
                create=True,
                writable=True,
            )
        elif name == "validate_storage":
            result = await asyncio.to_thread(self.state_store.validate_storage, db_path=str(params["db_path"]))
        elif name == "build_resume_state":
            result = await asyncio.to_thread(
                self.state_store.build_resume_state,
                settings=self._settings_from_params(params),
                fingerprint_payload=dict(params.get("fingerprint") or {}),
                create_new=bool(params.get("create_new")),
            )
        elif name == "list_account_contexts":
            result = await asyncio.to_thread(self._list_account_contexts, params)
        elif name == "select_account_context":
            result = await asyncio.to_thread(self._select_account_context, params)
        elif name == "refresh_manual":
            self._require_runtime_idle(name)
            result = await asyncio.to_thread(self._build_manual_preview, params)
        elif name == "preflight_manual":
            self._require_runtime_idle(name)
            result = await asyncio.to_thread(self._preflight_manual, params)
        elif name == "execute_manual":
            self._require_runtime_idle(name)
            result = await asyncio.to_thread(self._execute_manual, params)
        elif name == "start_runtime":
            result = await asyncio.to_thread(self.runtime_coordinator.start, self._runtime_config(params))
        elif name == "stop_runtime":
            await asyncio.to_thread(self.runtime_coordinator.stop)
            result = {"stopped": True}
        elif name == "set_live_enabled":
            await asyncio.to_thread(self.runtime_coordinator.set_live_enabled, bool(params.get("enabled")))
            result = {"live_enabled": bool(params.get("enabled"))}
        elif name == "approve_pending":
            pending = await asyncio.to_thread(self.runtime_coordinator.approve_pending_live_order)
            result = asdict(pending)
        elif name == "reject_pending":
            pending = await asyncio.to_thread(self.runtime_coordinator.reject_pending_live_order)
            result = asdict(pending)
        elif name == "load_telemetry":
            result = await asyncio.to_thread(self._load_telemetry, params)
        else:
            raise RuntimeError(f"unknown command: {name}")
        return {"type": "response", "id": request_id, "ok": True, "result": result}

    async def _drain_runtime_events(self) -> None:
        while True:
            events = await asyncio.to_thread(self.runtime_coordinator.drain_events)
            if events and self._clients:
                payloads = [
                    {"type": "event", "name": event.kind, "payload": {"message": event.message, **event.payload}}
                    for event in events
                ]
                disconnected = []
                for websocket in list(self._clients):
                    try:
                        for payload in payloads:
                            await websocket.send(json.dumps(payload, default=str))
                    except Exception:
                        disconnected.append(websocket)
                for websocket in disconnected:
                    self._clients.discard(websocket)
            await asyncio.sleep(0.2)

    def _build_manual_preview(self, params: dict[str, Any]) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            snapshot = self._load_manual_snapshot(adapter, params)
            manual = self._manual_order_snapshot(snapshot, params, adapter)
            sizing = self.risk_engine.compute_position_size(
                PositionSizeRequest(
                    account=snapshot.account,
                    symbol=snapshot.symbol_snapshot,
                    policy=snapshot.risk_policy,
                    stop_distance_points=self._stop_distance(snapshot, params),
                    trading_style=TradingStyle(params["trading_style"]),
                    capital_allocation=self._allocation(params),
                )
            )
            return {
                "snapshot": self._snapshot_payload(snapshot),
                "manual_order_snapshot": manual,
                "risk_sizing_snapshot": {
                    "accepted": sizing.accepted,
                    "final_lot": sizing.normalized_volume,
                    "raw_lot_before_broker_rounding": sizing.raw_volume,
                    "effective_risk_pct": sizing.effective_risk_pct,
                    "risk_cash_budget_usd": sizing.risk_cash_budget,
                    "estimated_loss_at_final_lot_usd": sizing.estimated_loss_cash,
                    "why_blocked": sizing.rejection_reason or "n/a",
                },
            }
        finally:
            self._shutdown_adapter(adapter)

    def _preflight_manual(self, params: dict[str, Any]) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            snapshot = self._load_manual_snapshot(adapter, params)
            manual = self._manual_order_snapshot(snapshot, params, adapter)
            if not manual["accepted"]:
                return {
                    "status": "REJECTED",
                    "detail": manual["why_blocked"],
                    "snapshot": self._snapshot_payload(snapshot),
                    "manual_order_snapshot": manual,
                }
            runtime = MT5ExecutionRuntime(adapter=adapter, allow_live_orders=False)
            size_result = self._manual_size_result(manual, params)
            result = runtime.preflight(snapshot, self._intent(snapshot, params, "manual preflight"), size_result)
            result["snapshot"] = self._snapshot_payload(snapshot)
            result["manual_order_snapshot"] = manual
            return result
        finally:
            self._shutdown_adapter(adapter)

    def _execute_manual(self, params: dict[str, Any]) -> dict[str, Any]:
        adapter = self.adapter_factory()
        try:
            snapshot = self._load_manual_snapshot(adapter, params)
            manual = self._manual_order_snapshot(snapshot, params, adapter)
            if not manual["accepted"]:
                return {
                    "status": "REJECTED",
                    "detail": manual["why_blocked"],
                    "snapshot": self._snapshot_payload(snapshot),
                    "manual_order_snapshot": manual,
                }
            runtime = MT5ExecutionRuntime(adapter=adapter, allow_live_orders=bool(params.get("live_enabled")))
            size_result = self._manual_size_result(manual, params)
            result = runtime.execute(snapshot, self._intent(snapshot, params, "manual execute"), size_result)
            result["snapshot"] = self._snapshot_payload(snapshot)
            result["manual_order_snapshot"] = manual
            return result
        finally:
            self._shutdown_adapter(adapter)

    def _load_telemetry(self, params: dict[str, Any]) -> dict[str, Any]:
        db_path = str(Path(str(params["db_path"])).expanduser())
        store = RuntimeStore(db_path)
        run_id = params.get("run_id") or self.runtime_coordinator.run_id
        overview = store.fetch_latest_run_overview(run_id=run_id or None) or store.fetch_latest_run_overview()
        if overview is None:
            return {"overview": None}
        run_id = str(overview.get("run_id") or "")
        health = store.fetch_execution_health_summary(run_id=run_id, limit=50)
        inputs = store.fetch_runtime_validation_inputs(run_id=run_id)
        report = build_runtime_validation_report(
            inputs["position_events"],
            inputs["execution_events"],
            starting_equity=float(inputs.get("starting_equity") or 0.0),
        )
        return {
            "overview": overview,
            "health": health,
            "validation": {
                "total_trades": report.validation_summary.total_trades,
                "win_rate": report.validation_summary.win_rate,
                "profit_factor": report.validation_summary.profit_factor,
                "expectancy_r": report.validation_summary.expectancy_r,
                "warnings": report.validation_summary.warnings + report.execution_quality.warnings,
            },
            "lifecycle_rows": inputs["lifecycle_rows"][:10],
        }

    def _load_runtime_state(self, params: dict[str, Any]) -> dict[str, Any]:
        settings = self._settings_from_params(params)
        runtime_state = self._load_json_dict(self.state_store.runtime_state_path)
        if not runtime_state:
            return {"exists": False, "runtime_state": None, "binding": None}
        return {
            "exists": True,
            "runtime_state": runtime_state,
            "binding": self._binding_from_runtime_state(settings, runtime_state),
        }

    def _list_account_contexts(self, params: dict[str, Any]) -> dict[str, Any]:
        settings = self._settings_from_params(params)
        fingerprint = AccountFingerprint.from_payload(dict(params.get("fingerprint") or {}))
        context_root = Path(settings.ai_context_root).expanduser()
        context_root.mkdir(parents=True, exist_ok=True)

        mapping = self._load_json_dict(self.state_store.account_context_map_path)
        runtime_state = self._load_json_dict(self.state_store.runtime_state_path)
        base_key = fingerprint.key
        mapped_context_key = self._optional_str(str(mapping.get(base_key) or ""))
        active_context_key = self._optional_str(str(runtime_state.get("context_key") or ""))

        candidate_keys: list[str] = []
        if mapped_context_key:
            candidate_keys.append(mapped_context_key)
        candidate_keys.append(base_key)
        prefix = f"{base_key}_"
        for child in context_root.iterdir():
            if child.is_dir() and (child.name == base_key or child.name.startswith(prefix)):
                candidate_keys.append(child.name)

        contexts: list[dict[str, Any]] = []
        seen: set[str] = set()
        for context_key in sorted(candidate_keys, key=self._context_sort_key):
            if not context_key or context_key in seen:
                continue
            seen.add(context_key)
            context_path = context_root / context_key
            contexts.append(
                {
                    **self._context_binding_payload(
                        fingerprint=fingerprint,
                        context_key=context_key,
                        context_path=context_path,
                        mapping_source="listed",
                        existed=context_path.exists(),
                        created_now=False,
                    ),
                    "is_mapped": context_key == mapped_context_key,
                    "is_active": context_key == active_context_key,
                }
            )

        return {
            "fingerprint": fingerprint.to_dict(),
            "base_context_key": base_key,
            "mapped_context_key": mapped_context_key,
            "active_context_key": active_context_key,
            "contexts": contexts,
        }

    def _select_account_context(self, params: dict[str, Any]) -> dict[str, Any]:
        context_key = self._optional_str(str(params.get("context_key") or ""))
        settings = self._settings_from_params(params)
        fingerprint = AccountFingerprint.from_payload(dict(params.get("fingerprint") or {}))
        if context_key is None:
            return self.state_store.build_resume_state(
                settings=settings,
                fingerprint_payload=fingerprint.to_dict(),
                create_new=bool(params.get("create_new")),
            )

        base_key = fingerprint.key
        if not self._context_matches_fingerprint(base_key, context_key):
            raise RuntimeError("Context akun tidak cocok dengan fingerprint aktif.")

        candidate = self._context_path_from_key(settings, context_key)
        if not candidate.exists():
            raise RuntimeError(f"Context akun tidak ditemukan: {context_key}")
        if not candidate.is_dir():
            raise RuntimeError("Context akun harus berupa folder.")

        self.state_store._ensure_context_structure(candidate, fingerprint)

        mapping = self._load_json_dict(self.state_store.account_context_map_path)
        mapping[base_key] = context_key
        self._dump_json_dict(self.state_store.account_context_map_path, mapping)

        binding = self._context_binding_payload(
            fingerprint=fingerprint,
            context_key=context_key,
            context_path=candidate,
            mapping_source="selected",
            existed=True,
            created_now=False,
        )
        runtime_state = self._write_runtime_state(fingerprint=fingerprint, binding=binding)
        return {
            "ok": True,
            "detail": f"Context akun dipilih: {candidate.resolve()}",
            "binding": binding,
            "runtime_state": runtime_state,
        }

    def _manual_size_result(self, manual_snapshot: dict[str, Any], params: dict[str, Any]):
        return SimpleNamespace(
            accepted=True,
            mode=OperatingMode.RECOMMEND,
            capital_base_cash=float(manual_snapshot.get("allocation_cap_usd") or 0.0),
            recommended_minimum_allocation_cash=0.0,
            effective_risk_pct=0.0,
            risk_cash_budget=0.0,
            normalized_volume=float(manual_snapshot.get("final_lot") or 0.0),
            estimated_loss_cash=0.0,
            stop_distance_points=self._stop_distance(None, params),
            rejection_reason=None,
            warnings=[],
        )

    @staticmethod
    def _snapshot_payload(snapshot) -> dict[str, Any]:
        return {
            "symbol": snapshot.symbol,
            "bid": snapshot.bid,
            "ask": snapshot.ask,
            "spread_points": snapshot.spread_points,
            "equity": snapshot.account.equity,
            "free_margin": snapshot.account.free_margin,
            "stops_level_points": snapshot.symbol_snapshot.stops_level_points,
            "trade_mode": snapshot.symbol_snapshot.trade_mode,
            "execution_mode": snapshot.symbol_snapshot.execution_mode,
            "filling_mode": snapshot.symbol_snapshot.filling_mode,
            "tick_time": snapshot.context.get("tick_time"),
            "account_fingerprint": snapshot.context.get("account_fingerprint"),
        }

    def _intent(self, snapshot, params: dict[str, Any], reason: str) -> AIIntent:
        side = str(params["side"])
        return AIIntent(
            action=DecisionAction.OPEN,
            side=side,
            reason=reason,
            stop_distance_points=self._stop_distance(snapshot, params),
            entry_price=snapshot.ask if side == "buy" else snapshot.bid,
        )

    def _provider(self, adapter, params: dict[str, Any]) -> MT5SnapshotProvider:
        return MT5SnapshotProvider(
            adapter=adapter,
            symbol=str(params["symbol"]),
            timeframe=str(params["timeframe"]),
            risk_policy=self.risk_policy,
            trading_style=TradingStyle(params["trading_style"]),
            stop_distance_points=self._stop_distance(None, params),
            capital_allocation=self._allocation(params),
            session_state="manual",
            news_state="unknown",
        )

    def _load_manual_snapshot(self, adapter, params: dict[str, Any]):
        snapshot = self._provider(adapter, params).get_snapshot()
        return self._refresh_snapshot_tick(snapshot, adapter)

    @staticmethod
    def _refresh_snapshot_tick(snapshot, adapter):
        tick = adapter.load_price_tick(snapshot.symbol)
        bid = float(tick.bid or snapshot.bid or snapshot.symbol_snapshot.bid or 0.0)
        ask = float(tick.ask or snapshot.ask or snapshot.symbol_snapshot.ask or 0.0)
        symbol_snapshot = replace(
            snapshot.symbol_snapshot,
            bid=bid,
            ask=ask,
            price=ask or bid or snapshot.symbol_snapshot.price,
        )
        spread_points = snapshot.spread_points
        point = float(symbol_snapshot.point or 0.0)
        if point > 0 and ask > 0 and bid > 0:
            spread_points = (ask - bid) / point
        context = dict(snapshot.context)
        context["tick_time"] = tick.time
        return replace(
            snapshot,
            bid=bid,
            ask=ask,
            spread_points=spread_points,
            symbol_snapshot=symbol_snapshot,
            context=context,
        )

    def _stop_distance(self, snapshot, params: dict[str, Any]) -> float:
        current = float(params.get("stop_distance_points") or 0.0)
        if snapshot is None:
            return current
        stop_min = float(snapshot.symbol_snapshot.stops_level_points or 0.0)
        return max(current, stop_min) if stop_min > 0 else current

    def _allocation(self, params: dict[str, Any]) -> CapitalAllocation:
        return CapitalAllocation(
            mode=CapitalAllocationMode(str(params["capital_mode"])),
            value=float(params["capital_value"]),
        )

    def _manual_order_snapshot(self, snapshot, params: dict[str, Any], adapter) -> dict[str, Any]:
        symbol = snapshot.symbol_snapshot
        side = str(params["side"])
        lot_mode = str(params.get("lot_mode") or "auto_max")
        order_price = float(snapshot.ask if side == "buy" else snapshot.bid)
        account_equity = max(snapshot.account.equity, 0.0)
        allocation = self._allocation(params)
        if allocation.mode is CapitalAllocationMode.FULL_EQUITY:
            allocation_cap = account_equity
        elif allocation.mode is CapitalAllocationMode.PERCENT_EQUITY:
            allocation_cap = account_equity * (min(max(allocation.value, 0.0), 100.0) / 100.0)
        else:
            allocation_cap = min(max(allocation.value, 0.0), account_equity)
        min_lot = float(symbol.volume_min or 0.0)
        max_lot = float(symbol.volume_max or 0.0)
        step = float(symbol.volume_step or 0.0)
        available_budget = min(allocation_cap, float(snapshot.account.free_margin))
        if min_lot <= 0 or max_lot <= 0 or step <= 0 or order_price <= 0:
            return {"accepted": False, "final_lot": 0.0, "why_blocked": "symbol volume or price configuration is invalid"}
        margin_min = adapter.estimate_margin(snapshot.symbol, min_lot, side, order_price)
        if not margin_min.success:
            return {"accepted": False, "final_lot": 0.0, "why_blocked": margin_min.detail}
        if margin_min.required_margin > available_budget:
            return {
                "accepted": False,
                "final_lot": 0.0,
                "allocation_cap_usd": allocation_cap,
                "available_margin_cap_usd": available_budget,
                "broker_min_lot": min_lot,
                "broker_max_lot": max_lot,
                "broker_lot_step": step,
                "margin_for_min_lot_usd": margin_min.required_margin,
                "why_blocked": "allocation cannot cover broker minimum lot margin",
            }
        affordable_max_lot = min_lot
        margin_for_final = margin_min.required_margin
        current = min_lot
        max_steps = int(round((max_lot - min_lot) / step)) + 1
        for _ in range(max_steps):
            next_lot = round(current + step, 8)
            if next_lot > max_lot + 1e-9:
                break
            margin = adapter.estimate_margin(snapshot.symbol, next_lot, side, order_price)
            if not margin.success or margin.required_margin > available_budget:
                break
            affordable_max_lot = next_lot
            margin_for_final = margin.required_margin
            current = next_lot
        requested_lot = 0.0
        resized = False
        why_blocked = "n/a"
        final_lot = affordable_max_lot
        if lot_mode == "manual":
            requested_lot = float(params.get("manual_lot") or 0.0)
            if requested_lot <= 0:
                return {"accepted": False, "final_lot": 0.0, "why_blocked": "manual lot must be positive"}
            normalized_requested = round((int(max(requested_lot, min_lot) / step) * step), 8)
            if normalized_requested < min_lot:
                normalized_requested = min_lot
            if normalized_requested > affordable_max_lot:
                resized = True
                why_blocked = "manual lot resized down to max allowed by capital, margin, and broker"
            elif abs(normalized_requested - requested_lot) > 1e-9:
                resized = True
                why_blocked = "manual lot normalized to broker minimum / step"
            final_lot = min(normalized_requested, affordable_max_lot)
            margin = adapter.estimate_margin(snapshot.symbol, final_lot, side, order_price)
            if margin.success:
                margin_for_final = margin.required_margin
        return {
            "accepted": final_lot > 0,
            "lot_mode": lot_mode,
            "requested_lot": requested_lot,
            "final_lot": final_lot,
            "allocation_cap_usd": allocation_cap,
            "available_margin_cap_usd": available_budget,
            "broker_min_lot": min_lot,
            "broker_max_lot": max_lot,
            "broker_lot_step": step,
            "margin_for_min_lot_usd": margin_min.required_margin,
            "margin_for_final_lot_usd": margin_for_final,
            "order_price": order_price,
            "resized_down": resized,
            "manual_order_result": "ok" if final_lot > 0 else "blocked",
            "why_blocked": why_blocked if final_lot > 0 else "allocation cannot cover broker minimum lot margin",
        }

    def _probe_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": str(params["symbol"]),
            "timeframe": str(params["timeframe"]),
            "trading_style": TradingStyle(params["trading_style"]),
            "stop_distance_points": float(params["stop_distance_points"]),
            "capital_allocation": self._allocation(params),
        }

    def _runtime_config(self, params: dict[str, Any]) -> DesktopRuntimeConfig:
        poll_interval = int(float(params.get("poll_interval_seconds") or 30))
        return DesktopRuntimeConfig(
            symbol=str(params["symbol"]),
            timeframe=str(params["timeframe"]),
            trading_style=TradingStyle(str(params["trading_style"])),
            stop_distance_points=float(params["stop_distance_points"]),
            capital_allocation=CapitalAllocation(
                mode=CapitalAllocationMode(str(params["capital_mode"])),
                value=float(params["capital_value"]),
            ),
            db_path=str(Path(str(params["db_path"])).expanduser()),
            codex_executable=str(params.get("codex_command") or "codex"),
            codex_model=params.get("model"),
            codex_cwd=params.get("codex_cwd"),
            codex_timeout_seconds=int(params.get("codex_timeout_seconds") or 60),
            poll_interval_seconds=poll_interval,
            session_state=str(params.get("session_state") or "desktop_runtime"),
            news_state=str(params.get("news_state") or "unknown"),
            run_id=str(params["run_id"]) if params.get("run_id") else None,
            ai_workspace_path=self._optional_str(str(params.get("ai_workspace_path") or "")),
            ai_documents_path=self._optional_str(str(params.get("ai_documents_path") or "")),
            ai_context_path=self._optional_str(str(params.get("ai_context_path") or params.get("ai_context_root") or "")),
            resume_prompt_path=self._optional_str(str(params.get("resume_prompt_path") or "")),
            behavior_profile_path=self._optional_str(str(params.get("behavior_profile_path") or "")),
            account_fingerprint=dict(params.get("account_fingerprint") or {}) or None,
        )

    def _require_runtime_idle(self, command_name: str) -> None:
        if self.runtime_coordinator.is_running:
            raise RuntimeError(
                f"{command_name} is disabled while runtime is running; stop runtime before manual MT5 actions"
            )

    def _codex_kwargs(self, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "executable": str(params.get("codex_command") or params.get("ai_runtime_command") or "codex"),
            "model": params.get("model") or params.get("default_model"),
            "cwd": params.get("codex_cwd") or params.get("ai_workspace_path"),
            "timeout_seconds": int(params.get("timeout_seconds") or params.get("codex_timeout_seconds") or 60),
        }

    @staticmethod
    def _shutdown_adapter(adapter: Any | None) -> None:
        if adapter is None:
            return
        shutdown = getattr(adapter, "shutdown", None)
        if callable(shutdown):
            shutdown()

    def _settings_from_params(self, params: dict[str, Any]) -> OperatorRuntimeSettings:
        current = self.state_store.load_runtime_settings()
        payload = current.to_dict()
        for key in payload:
            if key in params and params[key] is not None:
                payload[key] = params[key]
        if "model" in params and params.get("model") is not None:
            payload["default_model"] = params["model"]
        if "codex_command" in params and params.get("codex_command") is not None:
            payload["ai_runtime_command"] = params["codex_command"]
        if "codex_cwd" in params and params.get("codex_cwd") is not None:
            payload["ai_workspace_path"] = params["codex_cwd"]
        return OperatorRuntimeSettings(**payload)

    @staticmethod
    def _optional_str(value: str) -> str | None:
        normalized = value.strip()
        return normalized or None

    def _binding_from_runtime_state(
        self,
        settings: OperatorRuntimeSettings,
        runtime_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        fingerprint_payload = dict(runtime_state.get("active_account_fingerprint") or {})
        if not fingerprint_payload:
            return None
        fingerprint = AccountFingerprint.from_payload(fingerprint_payload)
        context_key = self._optional_str(str(runtime_state.get("context_key") or ""))
        context_path_raw = self._optional_str(str(runtime_state.get("context_path") or ""))
        if context_key is None and context_path_raw is None:
            return None
        context_path = Path(context_path_raw).expanduser() if context_path_raw else self._context_path_from_key(settings, context_key or "")
        if context_key is None:
            context_key = context_path.name
        return self._context_binding_payload(
            fingerprint=fingerprint,
            context_key=context_key,
            context_path=context_path,
            mapping_source="runtime_state",
            existed=context_path.exists(),
            created_now=False,
        )

    def _write_runtime_state(
        self,
        *,
        fingerprint: AccountFingerprint,
        binding: dict[str, Any],
    ) -> dict[str, Any]:
        runtime_state = {
            "active_account_fingerprint": fingerprint.to_dict(),
            "context_key": binding["context_key"],
            "context_path": binding["context_path"],
            "last_runtime_state": "ready",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._dump_json_dict(self.state_store.runtime_state_path, runtime_state)
        return runtime_state

    def _context_path_from_key(self, settings: OperatorRuntimeSettings, context_key: str) -> Path:
        candidate_key = context_key.strip()
        if not candidate_key:
            raise RuntimeError("context_key wajib diisi.")
        path_key = Path(candidate_key)
        if path_key.name != candidate_key or any(part in {"..", "."} for part in path_key.parts):
            raise RuntimeError("context_key tidak valid.")
        return Path(settings.ai_context_root).expanduser() / candidate_key

    @staticmethod
    def _context_matches_fingerprint(base_key: str, context_key: str) -> bool:
        return context_key == base_key or context_key.startswith(f"{base_key}_")

    @staticmethod
    def _context_sort_key(context_key: str) -> tuple[int, str]:
        suffix = 0
        if "_" in context_key:
            _, maybe_number = context_key.rsplit("_", 1)
            if maybe_number.isdigit():
                suffix = int(maybe_number)
        return (suffix, context_key)

    @staticmethod
    def _load_json_dict(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _dump_json_dict(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    @staticmethod
    def _context_binding_payload(
        *,
        fingerprint: AccountFingerprint,
        context_key: str,
        context_path: Path,
        mapping_source: str,
        existed: bool,
        created_now: bool,
    ) -> dict[str, Any]:
        resolved = context_path.resolve()
        return {
            "fingerprint": fingerprint.to_dict(),
            "context_key": context_key,
            "context_path": str(resolved),
            "existed": existed,
            "created_now": created_now,
            "mapping_source": mapping_source,
            "profile_path": str((resolved / "profile.yaml").resolve()),
            "latest_summary_path": str((resolved / "memory" / "latest_summary.md").resolve()),
            "open_issues_path": str((resolved / "memory" / "open_issues.md").resolve()),
            "last_session_path": str((resolved / "memory" / "last_session.json").resolve()),
            "resume_prompt_path": str((resolved / "resume" / "resume_prompt.md").resolve()),
            "broker_notes_path": str((resolved / "documents" / "broker_notes.md").resolve()),
            "operator_notes_path": str((resolved / "documents" / "operator_notes.md").resolve()),
        }


async def serve_forever() -> None:
    service = BotEaWebSocketService()
    await service.start()
    try:
        await asyncio.Future()
    finally:
        await service.stop()


def main() -> None:
    asyncio.run(serve_forever())


if __name__ == "__main__":
    main()
