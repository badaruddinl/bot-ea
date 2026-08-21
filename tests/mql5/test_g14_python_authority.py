from __future__ import annotations

import json
from pathlib import Path

import pytest

from gold_portfolio.config import load_worker_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "relative_path",
    [
        "config/final/goldi/portfolio.json",
        "config/final/goldm/portfolio.json",
        "config/validation/goldi/portfolio-demo.json",
        "config/validation/goldi/portfolio-shadow.json",
        "config/validation/goldm/portfolio-demo.json",
        "config/validation/goldm/portfolio-read-only.json",
        "config/validation/goldm/portfolio-shadow.json",
    ],
)
def test_all_migrated_portfolios_have_explicit_non_python_authority(
    relative_path: str,
) -> None:
    payload = json.loads((ROOT / relative_path).read_text(encoding="utf-8"))

    assert payload["order_authority"] in {"disabled", "mql5"}


def test_python_mt5_session_contains_no_order_mutation_call() -> None:
    source = (ROOT / "src/gold_portfolio/mt5_session.py").read_text(encoding="utf-8")

    for forbidden in (
        ".order_send(",
        ".order_check(",
        ".order_calc_margin(",
        "TRADE_ACTION_DEAL",
    ):
        assert forbidden not in source


def test_loader_rejects_python_order_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOLDI_MT5_TERMINAL_PATH", "C:/Goldi/terminal64.exe")
    monkeypatch.setenv("GOLDI_MT5_LOGIN", "108098316")
    monkeypatch.setenv("GOLDI_MT5_SERVER", "XMGlobal-MT5 5")
    portfolio = json.loads((ROOT / "config/final/goldi/portfolio.json").read_text(encoding="utf-8"))
    portfolio["order_authority"] = "python"
    portfolio_path = tmp_path / "portfolio.json"
    portfolio_path.write_text(json.dumps(portfolio), encoding="utf-8")
    worker = json.loads((ROOT / "config/final/goldi/worker.json").read_text(encoding="utf-8"))
    worker["portfolio_config"] = str(portfolio_path)
    worker["pinned_files"] = {}
    worker_path = tmp_path / "worker.json"
    worker_path.write_text(json.dumps(worker), encoding="utf-8")

    with pytest.raises(ValueError, match="cannot own order authority"):
        load_worker_config(worker_path)
