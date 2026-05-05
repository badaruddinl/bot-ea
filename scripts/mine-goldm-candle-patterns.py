import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import numpy as np
import pandas as pd


@dataclass
class EvalResult:
    name: str
    side: str
    horizon: int
    count: int
    mean: float
    win_rate: float
    profit_factor: float
    total: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mine raw GOLDm# M1 candle patterns from MT5 history.")
    parser.add_argument("--symbol", default="GOLDm#")
    parser.add_argument("--terminal", default=r"C:\Program Files\MetaTrader 5\terminal64.exe")
    parser.add_argument("--from-date", default="2024-05-17")
    parser.add_argument("--to-date", default=None)
    parser.add_argument("--point", type=float, default=0.01)
    parser.add_argument("--min-count", type=int, default=80)
    parser.add_argument("--out-dir", default=r"data\research\goldm_candle_mining")
    return parser.parse_args()


def utc_date(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def initialize_mt5(terminal: str, symbol: str) -> None:
    if not mt5.initialize(path=terminal):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    if not mt5.symbol_select(symbol, True):
        raise RuntimeError(f"Failed to select symbol {symbol}: {mt5.last_error()}")


def fetch_rates(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    chunks = []
    cursor = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while cursor < end_ts:
        chunk_end = min(cursor + pd.Timedelta(days=31), end_ts)
        rates = mt5.copy_rates_range(symbol, mt5.TIMEFRAME_M1, cursor.to_pydatetime(), chunk_end.to_pydatetime())
        if rates is not None and len(rates) > 0:
            chunks.append(pd.DataFrame(rates))
        cursor = chunk_end

    if not chunks:
        raise RuntimeError(f"No M1 rates returned for {symbol}")

    frame = pd.concat(chunks, ignore_index=True)
    frame = frame.drop_duplicates(subset=["time"]).sort_values("time").reset_index(drop=True)
    frame["time"] = pd.to_datetime(frame["time"], unit="s", utc=True)
    return frame


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def add_features(df: pd.DataFrame, point: float) -> pd.DataFrame:
    out = df.copy()
    spread_price = out["spread"].astype(float) * point
    if spread_price.quantile(0.50) <= 0:
        spread_price = pd.Series(point * 30.0, index=out.index)
    out["spread_price"] = spread_price.clip(lower=point)

    out["range"] = (out["high"] - out["low"]).clip(lower=point)
    out["body"] = out["close"] - out["open"]
    out["body_abs"] = out["body"].abs()
    out["body_frac"] = out["body_abs"] / out["range"]
    out["upper_wick"] = out["high"] - out[["open", "close"]].max(axis=1)
    out["lower_wick"] = out[["open", "close"]].min(axis=1) - out["low"]
    out["hour"] = out["time"].dt.hour
    out["weekday"] = out["time"].dt.weekday

    out["dir"] = np.where(out["body"] > 0, "U", np.where(out["body"] < 0, "D", "N"))
    out["shape"] = np.select(
        [
            out["body_frac"] >= 0.70,
            out["body_frac"] <= 0.20,
            out["upper_wick"] > out["lower_wick"] * 1.5,
            out["lower_wick"] > out["upper_wick"] * 1.5,
        ],
        ["FULL", "DOJI", "UPWICK", "LOWWICK"],
        default="MID",
    )

    for span in [5, 9, 13, 20, 50, 200]:
        out[f"ema{span}"] = ema(out["close"], span)
    for period in [7, 14]:
        out[f"rsi{period}"] = rsi(out["close"], period)

    prev_close = out["close"].shift(1)
    tr = pd.concat(
        [
            out["high"] - out["low"],
            (out["high"] - prev_close).abs(),
            (out["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    out["atr14"] = tr.ewm(alpha=1.0 / 14.0, adjust=False).mean()
    out["atr60_med"] = tr.rolling(60, min_periods=20).median()
    out["atr_spread"] = out["atr14"] / out["spread_price"]
    mid = out["close"].rolling(20, min_periods=20).mean()
    std = out["close"].rolling(20, min_periods=20).std()
    out["bb_upper"] = mid + 2.0 * std
    out["bb_lower"] = mid - 2.0 * std

    for n in [3, 5, 8, 10]:
        out[f"prev_high_{n}"] = out["high"].shift(1).rolling(n, min_periods=n).max()
        out[f"prev_low_{n}"] = out["low"].shift(1).rolling(n, min_periods=n).min()

    dirs = out["dir"].tolist()
    shapes = out["shape"].tolist()
    for lookback in range(1, 11):
        seq = [None] * len(out)
        shaped = [None] * len(out)
        for i in range(lookback - 1, len(out)):
            raw_seq = "".join(dirs[i - lookback + 1 : i + 1])
            seq[i] = raw_seq
            if lookback <= 4:
                shaped[i] = raw_seq + "|" + shapes[i]
        out[f"seq_{lookback}"] = seq
        if lookback <= 4:
            out[f"shape_seq_{lookback}"] = shaped

    return out


def add_forward_returns(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    out = df.copy()
    entry = out["open"].shift(-1)
    cost = out["spread_price"].shift(-1)
    for horizon in horizons:
        future_close = out["close"].shift(-(horizon + 1))
        out[f"long_h{horizon}"] = future_close - entry - cost
        out[f"short_h{horizon}"] = entry - future_close - cost
    return out


def evaluate_returns(name: str, side: str, horizon: int, returns: pd.Series) -> EvalResult:
    values = returns.replace([np.inf, -np.inf], np.nan).dropna()
    if values.empty:
        return EvalResult(name, side, horizon, 0, 0, 0, 0, 0)
    wins = values[values > 0]
    losses = values[values < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(losses.sum())
    pf = gross_profit / abs(gross_loss) if gross_loss < 0 else (999.0 if gross_profit > 0 else 0.0)
    return EvalResult(
        name=name,
        side=side,
        horizon=horizon,
        count=int(values.size),
        mean=float(values.mean()),
        win_rate=float((values > 0).mean()),
        profit_factor=float(pf),
        total=float(values.sum()),
    )


def result_dict(result: EvalResult) -> dict:
    return {
        "name": result.name,
        "side": result.side,
        "horizon": result.horizon,
        "count": result.count,
        "mean": round(result.mean, 6),
        "win_rate": round(result.win_rate, 4),
        "profit_factor": round(result.profit_factor, 4),
        "total": round(result.total, 4),
    }


def split_masks(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {
        "train": df["time"] < pd.Timestamp("2026-04-01", tz="UTC"),
        "oos_april": (df["time"] >= pd.Timestamp("2026-04-01", tz="UTC"))
        & (df["time"] < pd.Timestamp("2026-05-01", tz="UTC")),
        "latest": df["time"] >= pd.Timestamp("2026-05-01", tz="UTC"),
    }


def mine_raw_patterns(df: pd.DataFrame, masks: dict[str, pd.Series], min_count: int) -> list[dict]:
    records = []
    train_mask = masks["train"]
    pattern_cols = [f"seq_{i}" for i in range(1, 11)] + [f"shape_seq_{i}" for i in range(1, 5)]
    for col in pattern_cols:
        train = df[train_mask & df[col].notna()]
        for pattern, group in train.groupby(col):
            if len(group) < min_count:
                continue
            for horizon in [10, 20]:
                long_train = evaluate_returns(pattern, "long", horizon, group[f"long_h{horizon}"])
                short_train = evaluate_returns(pattern, "short", horizon, group[f"short_h{horizon}"])
                chosen = long_train if long_train.mean >= short_train.mean else short_train
                if chosen.count < min_count:
                    continue
                row = {"column": col, "pattern": pattern, "train": result_dict(chosen)}
                for split, mask in masks.items():
                    if split == "train":
                        continue
                    subset = df[mask & (df[col] == pattern)]
                    row[split] = result_dict(evaluate_returns(pattern, chosen.side, horizon, subset[f"{chosen.side}_h{horizon}"]))
                records.append(row)
    records.sort(key=lambda item: (item["train"]["mean"], item["train"]["profit_factor"], item["train"]["count"]), reverse=True)
    return records[:200]


def rule_signals(df: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    core_london = df["hour"].between(7, 11, inclusive="left")
    core_ny = df["hour"].between(13, 17, inclusive="left")
    core = core_london | core_ny
    tight_spread = df["spread_price"] <= df["spread_price"].quantile(0.35)
    good_atr_spread = df["atr_spread"] >= 5.0
    bullish = df["close"] > df["open"]
    bearish = df["close"] < df["open"]

    return {
        "ema5_13_rsi7_long": (
            "long",
            (df["ema5"] > df["ema13"]) & (df["rsi7"] > 50) & bullish,
        ),
        "ema5_13_rsi7_short": (
            "short",
            (df["ema5"] < df["ema13"]) & (df["rsi7"] < 50) & bearish,
        ),
        "ema9_20_momo_long": (
            "long",
            (df["ema9"] > df["ema20"]) & (df["rsi14"] > 52) & bullish,
        ),
        "ema9_20_momo_short": (
            "short",
            (df["ema9"] < df["ema20"]) & (df["rsi14"] < 48) & bearish,
        ),
        "ema50_200_momo_long": (
            "long",
            (df["ema50"] > df["ema200"]) & (df["close"] > df["ema50"]) & (df["rsi14"] > 52),
        ),
        "ema50_200_momo_short": (
            "short",
            (df["ema50"] < df["ema200"]) & (df["close"] < df["ema50"]) & (df["rsi14"] < 48),
        ),
        "rsi14_revert_long": ("long", (df["rsi14"] < 30) & (df["close"] < df["bb_lower"])),
        "rsi14_revert_short": ("short", (df["rsi14"] > 70) & (df["close"] > df["bb_upper"])),
        "breakout5_long": ("long", df["close"] > df["prev_high_5"]),
        "breakout5_short": ("short", df["close"] < df["prev_low_5"]),
        "breakout10_long": ("long", df["close"] > df["prev_high_10"]),
        "breakout10_short": ("short", df["close"] < df["prev_low_10"]),
        "core_ema9_20_long": (
            "long",
            core & tight_spread & good_atr_spread & (df["ema9"] > df["ema20"]) & (df["rsi14"] > 52) & bullish,
        ),
        "core_ema9_20_short": (
            "short",
            core & tight_spread & good_atr_spread & (df["ema9"] < df["ema20"]) & (df["rsi14"] < 48) & bearish,
        ),
        "london_breakout5_long": ("long", core_london & tight_spread & (df["close"] > df["prev_high_5"])),
        "london_breakout5_short": ("short", core_london & tight_spread & (df["close"] < df["prev_low_5"])),
        "ny_breakout5_long": ("long", core_ny & tight_spread & (df["close"] > df["prev_high_5"])),
        "ny_breakout5_short": ("short", core_ny & tight_spread & (df["close"] < df["prev_low_5"])),
    }


def evaluate_rules(df: pd.DataFrame, masks: dict[str, pd.Series], min_count: int) -> list[dict]:
    rows = []
    for rule_name, (side, signal) in rule_signals(df).items():
        for horizon in [10, 20]:
            row = {"rule": rule_name, "side": side, "horizon": horizon}
            for split, mask in masks.items():
                subset = df[mask & signal]
                result = evaluate_returns(rule_name, side, horizon, subset[f"{side}_h{horizon}"])
                row[split] = result_dict(result)
            if row["train"]["count"] >= min_count:
                rows.append(row)
    rows.sort(
        key=lambda item: (
            item["oos_april"]["mean"],
            item["oos_april"]["profit_factor"],
            item["train"]["count"],
        ),
        reverse=True,
    )
    return rows


def barrier_returns(df: pd.DataFrame, signal: pd.Series, side: str, horizon: int, tp: float, sl: float) -> pd.Series:
    values = []
    opens = df["open"].to_numpy()
    highs = df["high"].to_numpy()
    lows = df["low"].to_numpy()
    closes = df["close"].to_numpy()
    spreads = df["spread_price"].to_numpy()
    mask = signal.fillna(False).to_numpy()
    indexes = np.flatnonzero(mask)

    for i in indexes:
        entry_index = i + 1
        exit_index = i + horizon
        if entry_index >= len(df) or exit_index >= len(df):
            continue

        entry = opens[entry_index]
        spread = spreads[entry_index]
        outcome = None
        for j in range(entry_index, exit_index + 1):
            if side == "long":
                high_net = highs[j] - entry - spread
                low_net = lows[j] - entry - spread
                if low_net <= -sl:
                    outcome = -sl
                    break
                if high_net >= tp:
                    outcome = tp
                    break
            else:
                high_net = entry - lows[j] - spread
                low_net = entry - highs[j] - spread
                if low_net <= -sl:
                    outcome = -sl
                    break
                if high_net >= tp:
                    outcome = tp
                    break

        if outcome is None:
            if side == "long":
                outcome = closes[exit_index] - entry - spread
            else:
                outcome = entry - closes[exit_index] - spread
        values.append(outcome)

    return pd.Series(values, dtype=float)


def barrier_signal_set(df: pd.DataFrame) -> dict[str, tuple[str, pd.Series]]:
    signals = rule_signals(df)
    selected = {
        "rsi14_revert_long": signals["rsi14_revert_long"],
        "core_ema9_20_long": signals["core_ema9_20_long"],
        "ema9_20_momo_long": signals["ema9_20_momo_long"],
        "ema50_200_momo_short": signals["ema50_200_momo_short"],
        "breakout5_long": signals["breakout5_long"],
        "raw_seq9_up_long": ("long", df["seq_9"] == "UUUUUUUUU"),
    }
    return selected


def evaluate_barrier_rules(df: pd.DataFrame, masks: dict[str, pd.Series], min_count: int) -> list[dict]:
    rows = []
    configs = []
    for horizon in [10, 20]:
        for tp in [0.08, 0.12, 0.20, 0.30]:
            for sl in [0.20, 0.30, 0.50, 0.80]:
                configs.append((horizon, tp, sl))

    for rule_name, (side, signal) in barrier_signal_set(df).items():
        for horizon, tp, sl in configs:
            row = {"rule": rule_name, "side": side, "horizon": horizon, "tp": tp, "sl": sl}
            for split, mask in masks.items():
                split_signal = signal & mask
                result = evaluate_returns(rule_name, side, horizon, barrier_returns(df, split_signal, side, horizon, tp, sl))
                row[split] = result_dict(result)
            if row["train"]["count"] >= min_count:
                rows.append(row)

    rows.sort(
        key=lambda item: (
            item["oos_april"]["profit_factor"],
            item["oos_april"]["mean"],
            item["latest"]["profit_factor"],
            item["train"]["profit_factor"],
        ),
        reverse=True,
    )
    return rows


def write_markdown(path: Path, symbol: str, df: pd.DataFrame, raw: list[dict], rules: list[dict], barriers: list[dict]) -> None:
    lines = [
        f"# {symbol} Raw Candle Pattern Mining",
        "",
        f"Bars: `{len(df):,}`",
        f"Range: `{df['time'].min()}` to `{df['time'].max()}`",
        "",
        "Returns are measured from next M1 open to 10/20 candles forward, net of one entry spread approximation.",
        "",
        "## Top Raw Patterns By Train Expectancy",
        "",
        "| Pattern | Side | H | Train n | Train mean | Train PF | OOS n | OOS mean | OOS PF | Latest n | Latest mean | Latest PF |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in raw[:30]:
        train = item["train"]
        oos = item["oos_april"]
        latest = item["latest"]
        lines.append(
            f"| `{item['column']}={item['pattern']}` | {train['side']} | {train['horizon']} | "
            f"{train['count']} | {train['mean']} | {train['profit_factor']} | "
            f"{oos['count']} | {oos['mean']} | {oos['profit_factor']} | "
            f"{latest['count']} | {latest['mean']} | {latest['profit_factor']} |"
        )
    lines += [
        "",
        "## Indicator Rule Checks",
        "",
        "| Rule | Side | H | Train n | Train mean | Train PF | OOS n | OOS mean | OOS PF | Latest n | Latest mean | Latest PF |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in rules:
        train = item["train"]
        oos = item["oos_april"]
        latest = item["latest"]
        lines.append(
            f"| `{item['rule']}` | {item['side']} | {item['horizon']} | "
            f"{train['count']} | {train['mean']} | {train['profit_factor']} | "
            f"{oos['count']} | {oos['mean']} | {oos['profit_factor']} | "
            f"{latest['count']} | {latest['mean']} | {latest['profit_factor']} |"
        )
    lines += [
        "",
        "## Trading Barrier Checks",
        "",
        "Barrier checks approximate MT5 execution by entering on the next M1 open and charging one spread. If TP and SL are both inside the same candle, the SL is counted first.",
        "",
        "| Rule | Side | H | TP | SL | Train n | Train mean | Train PF | OOS n | OOS mean | OOS PF | Latest n | Latest mean | Latest PF |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for item in barriers[:40]:
        train = item["train"]
        oos = item["oos_april"]
        latest = item["latest"]
        lines.append(
            f"| `{item['rule']}` | {item['side']} | {item['horizon']} | "
            f"{item['tp']} | {item['sl']} | "
            f"{train['count']} | {train['mean']} | {train['profit_factor']} | "
            f"{oos['count']} | {oos['mean']} | {oos['profit_factor']} | "
            f"{latest['count']} | {latest['mean']} | {latest['profit_factor']} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    start = utc_date(args.from_date)
    end = datetime.now(timezone.utc) if args.to_date is None else utc_date(args.to_date)

    initialize_mt5(args.terminal, args.symbol)
    try:
        rates = fetch_rates(args.symbol, start, end)
        features = add_features(rates, args.point)
        dataset = add_forward_returns(features, [10, 20]).dropna().reset_index(drop=True)
        masks = split_masks(dataset)

        raw = mine_raw_patterns(dataset, masks, args.min_count)
        rules = evaluate_rules(dataset, masks, args.min_count)
        barriers = evaluate_barrier_rules(dataset, masks, args.min_count)

        rates_path = out_dir / f"{args.symbol.replace('#', 'hash')}_m1_features.parquet"
        dataset.to_parquet(rates_path, index=False)
        (out_dir / "raw_patterns.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
        (out_dir / "indicator_rules.json").write_text(json.dumps(rules, indent=2), encoding="utf-8")
        (out_dir / "barrier_rules.json").write_text(json.dumps(barriers, indent=2), encoding="utf-8")
        pd.DataFrame(barriers).to_csv(out_dir / "barrier_rules.csv", index=False)
        write_markdown(out_dir / "summary.md", args.symbol, dataset, raw, rules, barriers)

        print(f"bars={len(dataset)}")
        print(f"range={dataset['time'].min()}..{dataset['time'].max()}")
        print(f"summary={out_dir / 'summary.md'}")
        print(f"raw_patterns={out_dir / 'raw_patterns.json'}")
        print(f"indicator_rules={out_dir / 'indicator_rules.json'}")
        print(f"barrier_rules={out_dir / 'barrier_rules.json'}")
        print(f"features={rates_path}")
    finally:
        mt5.shutdown()


if __name__ == "__main__":
    main()
