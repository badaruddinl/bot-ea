from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Iterator

from .engine import RevisedBar, RevisedEngine, RevisedEngineConfig
from .replay import RevisedReplay


YAHOO_GOLD_PROXY = "GC=F"
YAHOO_PROXY_WARNING = (
    "GC=F is a COMEX futures proxy, not broker GOLD.i#. Its candles, session, "
    "spread, and price can differ; it cannot prove broker-exact outcomes."
)


def chunk_ranges(start: datetime, end: datetime, *, days: int = 7) -> Iterator[tuple[datetime, datetime]]:
    """Yield end-exclusive ranges small enough for Yahoo's intraday endpoint."""
    if end <= start:
        raise ValueError("end must be after start")
    if not 1 <= days <= 7:
        raise ValueError("intraday chunk size must be between 1 and 7 days")
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + timedelta(days=days), end)
        yield cursor, chunk_end
        cursor = chunk_end


def run_yfinance_research(
    *,
    start: datetime,
    end: datetime,
    server_timezone: timezone,
    output_dir: Path,
    ticker: str = YAHOO_GOLD_PROXY,
    downloader: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    # Optional research dependencies remain outside the live/shadow runtime path.
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import yfinance as yf

    download = downloader or yf.download
    frames = []
    source_start = start - timedelta(days=2)
    for chunk_start, chunk_end in chunk_ranges(source_start, end):
        frame = download(
            ticker,
            start=chunk_start,
            end=chunk_end,
            interval="1m",
            auto_adjust=False,
            progress=False,
            threads=False,
        )
        if frame is not None and not frame.empty:
            frames.append(_flatten_frame(frame, ticker))
    if not frames:
        raise RuntimeError(f"no Yahoo 1-minute data returned for {ticker}")

    m1 = pd.concat(frames).sort_index()
    m1 = m1[~m1.index.duplicated(keep="last")]
    if m1.index.tz is None:
        m1.index = m1.index.tz_localize(timezone.utc)
    m1 = m1.tz_convert(server_timezone)

    m5 = _resample(m1, "5min")
    h1 = _download_slow_frame(
        download,
        ticker=ticker,
        start=start - timedelta(days=60),
        end=end,
        interval="1h",
        timezone_value=server_timezone,
    )
    d1 = _download_slow_frame(
        download,
        ticker=ticker,
        start=start - timedelta(days=180),
        end=end,
        interval="1d",
        timezone_value=server_timezone,
    )

    report = RevisedReplay(RevisedEngine(RevisedEngineConfig(symbol=ticker))).run(
        m1_bars=_to_bars(m1),
        m5_bars=_to_bars(m5),
        h1_bars=_to_bars(h1),
        d1_bars=_to_bars(d1),
        from_time=start,
        to_time=end,
    )
    payload = {
        "data_source": "Yahoo Finance",
        "ticker": ticker,
        "broker_symbol": "GOLD.i#",
        "broker_exact": False,
        "warning": YAHOO_PROXY_WARNING,
        "requested_from": start.isoformat(),
        "requested_to": end.isoformat(),
        "actual_m1_from": m1.index.min().isoformat(),
        "actual_m1_to": m1.index.max().isoformat(),
        "m1_bars": int(len(m1)),
        "report": asdict(report),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "gc_f_replay.json").write_text(
        json.dumps(payload, default=_json_default, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    m1.to_csv(output_dir / "gc_f_m1.csv")
    _plot_diagnostics(plt, m1, report.outcomes, start, end, output_dir / "gc_f_diagnostics.png")
    return payload


def _flatten_frame(frame: Any, ticker: str) -> Any:
    if getattr(frame.columns, "nlevels", 1) > 1:
        frame = frame.copy()
        frame.columns = [str(column[0]) for column in frame.columns]
    required = ["Open", "High", "Low", "Close", "Volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise RuntimeError(f"Yahoo response for {ticker} lacks columns: {missing}")
    return frame[required].dropna(subset=["Open", "High", "Low", "Close"])


def _download_slow_frame(
    download: Callable[..., Any],
    *,
    ticker: str,
    start: datetime,
    end: datetime,
    interval: str,
    timezone_value: timezone,
) -> Any:
    frame = download(
        ticker,
        start=start,
        end=end,
        interval=interval,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    frame = _flatten_frame(frame, ticker)
    if frame.empty:
        raise RuntimeError(f"no Yahoo {interval} data returned for {ticker}")
    if frame.index.tz is None:
        frame.index = frame.index.tz_localize(timezone.utc)
    return frame.tz_convert(timezone_value)


def _resample(frame: Any, rule: str) -> Any:
    result = frame.resample(rule, label="left", closed="left").agg(
        {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    )
    return result.dropna(subset=["Open", "High", "Low", "Close"])


def _to_bars(frame: Any) -> list[RevisedBar]:
    return [
        RevisedBar(
            time=index.to_pydatetime(),
            open=float(row.Open),
            high=float(row.High),
            low=float(row.Low),
            close=float(row.Close),
            volume=float(row.Volume),
            spread=0.20,
        )
        for index, row in frame.iterrows()
    ]


def _plot_diagnostics(plt: Any, m1: Any, outcomes: Any, start: datetime, end: datetime, path: Path) -> None:
    view = m1.loc[(m1.index >= start) & (m1.index < end)].copy()
    view["Support"] = view["Low"].where(view["Low"] == view["Low"].rolling(5, center=True).min())
    view["Resistance"] = view["High"].where(view["High"] == view["High"].rolling(5, center=True).max())
    figure, axis = plt.subplots(figsize=(18, 8))
    axis.plot(view.index, view["Close"], color="#506784", linewidth=0.7, label="GC=F close")
    axis.scatter(view.index, view["Support"], color="#2ca02c", marker="^", s=10, label="diagnostic support")
    axis.scatter(view.index, view["Resistance"], color="#d62728", marker="v", s=10, label="diagnostic resistance")
    for outcome in outcomes:
        color = "#2ca02c" if outcome.outcome_r > 0 else "#d62728"
        axis.scatter(outcome.opened_at, outcome.entry, color=color, marker="o", s=35)
    low = int(view["Low"].min() // 10) * 10
    high = int(view["High"].max() // 10 + 1) * 10
    for level in range(low, high + 1, 10):
        axis.axhline(level, color="#9467bd", alpha=0.08, linewidth=0.6)
    axis.set_title("GOLDM_REVISED auxiliary replay — GC=F proxy (not broker GOLD.i#)")
    axis.set_ylabel("USD")
    axis.grid(alpha=0.15)
    axis.legend(loc="upper left")
    figure.tight_layout()
    figure.savefig(path, dpi=160)
    plt.close(figure)


def _json_default(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)
