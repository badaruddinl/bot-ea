from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from gold_engine_core import (  # noqa: E402
    DemoRuntimeBinding,
    RuntimeValidationBinding,
    load_demo_validation_manifest,
    load_named_profile,
    load_runtime_validation_manifest,
    validate_demo_binding,
    validate_runtime_binding,
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def probe(profile_id: str, output: Path) -> dict[str, object]:
    is_demo = profile_id == "GOLDI"
    filename = "GOLDI_DEMO.json" if is_demo else "GOLDM_REAL_READ_ONLY.json"
    manifest_path = REPOSITORY_ROOT / "config" / "validation_profiles" / filename
    if is_demo:
        demo_manifest = load_demo_validation_manifest(manifest_path)
        manifest = demo_manifest
    else:
        read_only_manifest = load_runtime_validation_manifest(manifest_path)
        manifest = read_only_manifest
    production = load_named_profile(REPOSITORY_ROOT, profile_id)
    terminal_path = os.environ.get(manifest.terminal_path_env, "").strip()
    login_text = os.environ.get(manifest.login_env, "").strip()
    server = os.environ.get(manifest.server_env, "").strip()
    if not terminal_path or not Path(terminal_path).is_file():
        raise RuntimeError("dedicated validation terminal path is missing")
    if not login_text.isdecimal() or not server:
        raise RuntimeError("dedicated validation login/server binding is missing")
    login = int(login_text)
    if is_demo:
        production_login_text = os.environ.get(production.terminal.expected_login_env, "").strip()
        production_login = int(production_login_text) if production_login_text.isdecimal() else None
        validate_demo_binding(
            demo_manifest,
            production,
            DemoRuntimeBinding(
                manifest.validation_profile_id,
                terminal_path,
                login,
                server,
                "demo",
                manifest.symbol,
            ),
            production_login=production_login,
        )
        access_mode = "demo_execution"
    else:
        access_mode = "read_only"
        validate_runtime_binding(
            read_only_manifest,
            production,
            RuntimeValidationBinding(
                manifest.validation_profile_id,
                terminal_path,
                login,
                server,
                "real",
                manifest.symbol,
                access_mode,
            ),
        )

    mt5 = importlib.import_module("MetaTrader5")
    started = perf_counter()
    initialized = (
        mt5.initialize(terminal_path, login=login, server=server)
        if is_demo
        else mt5.initialize(terminal_path)
    )
    if not initialized:
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        account = mt5.account_info()
        terminal = mt5.terminal_info()
        symbol = mt5.symbol_info(manifest.symbol)
        if account is None or terminal is None or symbol is None:
            raise RuntimeError("terminal/account/symbol metadata unavailable")
        if int(account.login) != login or str(account.server) != server:
            raise RuntimeError("runtime account binding changed after initialize")
        mode_constant = (
            int(getattr(mt5, "ACCOUNT_TRADE_MODE_DEMO", 0))
            if is_demo
            else int(getattr(mt5, "ACCOUNT_TRADE_MODE_REAL", 2))
        )
        trade_mode = "demo" if is_demo else "real"
        if int(account.trade_mode) != mode_constant:
            raise RuntimeError(f"runtime account is not {trade_mode.upper()}")
        if str(symbol.name) != manifest.symbol:
            raise RuntimeError("runtime symbol is not profile canonical")
        if is_demo and not mt5.symbol_select(manifest.symbol, True):
            raise RuntimeError(f"symbol selection failed: {mt5.last_error()}")
        tick = mt5.symbol_info_tick(manifest.symbol)
        if tick is None:
            raise RuntimeError(f"tick read failed: {mt5.last_error()}")
        bars: dict[str, object] = {}
        for timeframe_name in ("M1", "M5", "M15", "H1"):
            timeframe = getattr(mt5, f"TIMEFRAME_{timeframe_name}")
            rates = mt5.copy_rates_from_pos(manifest.symbol, timeframe, 1, 3)
            if rates is None or len(rates) < 1:
                raise RuntimeError(f"closed {timeframe_name} read failed: {mt5.last_error()}")
            bars[timeframe_name] = {
                "count": len(rates),
                "latest_closed_epoch": int(rates[-1]["time"]),
            }
        elapsed_ms = (perf_counter() - started) * 1000.0
        evidence = {
            "account_login_sha256": _sha256_text(str(account.login)),
            "account_server": str(account.server),
            "account_trade_mode": trade_mode,
            "access_mode": access_mode,
            "bars": bars,
            "captured_at": datetime.now(UTC).isoformat(),
            "latency_ms": round(elapsed_ms, 3),
            "orders_sent": 0,
            "order_api_calls": 0,
            "production_real_orders": "DISABLED",
            "profile_fingerprint": production.fingerprint,
            "profile_id": profile_id,
            "symbol": manifest.symbol,
            "terminal_build": int(getattr(terminal, "build", 0)),
            "terminal_executable_sha256": _sha256_file(Path(terminal_path)),
            "terminal_path_sha256": _sha256_text(str(Path(terminal_path).resolve()).casefold()),
            "tick": {
                "ask": float(tick.ask),
                "bid": float(tick.bid),
                "time_msc": int(getattr(tick, "time_msc", 0)),
            },
            "validation_profile_id": manifest.validation_profile_id,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            json.dumps(evidence, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("utf-8")
        output.write_bytes(raw)
        output.with_suffix(".sha256").write_bytes(
            f"{hashlib.sha256(raw).hexdigest()}  {output.name}\n".encode("ascii")
        )
        return evidence
    finally:
        mt5.shutdown()


def main() -> int:
    parser = argparse.ArgumentParser(description="G10 DEMO/read-only broker profile probe")
    parser.add_argument("--profile", required=True, choices=("GOLDI", "GOLDM"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    evidence = probe(args.profile, args.output)
    print(
        f"profile={evidence['profile_id']} validation={evidence['validation_profile_id']} "
        f"orders_sent=0 latency_ms={evidence['latency_ms']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
