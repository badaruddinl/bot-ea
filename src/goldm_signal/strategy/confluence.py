from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Candle:
    open: float
    high: float
    low: float
    close: float

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)


@dataclass(frozen=True, slots=True)
class ConfluenceResult:
    passed: bool
    votes: int
    reason: str


def is_doji(candle: Candle, *, maximum_body_ratio: float = 0.20) -> bool:
    if candle.range <= 0 or not 0 < maximum_body_ratio < 1:
        return False
    return candle.body / candle.range <= maximum_body_ratio


def is_morning_doji_star(
    first: Candle,
    middle: Candle,
    third: Candle,
    *,
    maximum_doji_body_ratio: float = 0.20,
) -> bool:
    if first.range <= 0:
        return False
    bearish_first = first.close < first.open and first.body / first.range >= 0.45
    doji_middle = is_doji(middle, maximum_body_ratio=maximum_doji_body_ratio)
    bullish_third = third.close > third.open and third.close >= (first.open + first.close) / 2
    star_located_low = max(middle.open, middle.close) <= max(first.open, first.close)
    return bearish_first and doji_middle and bullish_third and star_located_low


def is_evening_doji_star(
    first: Candle,
    middle: Candle,
    third: Candle,
    *,
    maximum_doji_body_ratio: float = 0.20,
) -> bool:
    if first.range <= 0:
        return False
    bullish_first = first.close > first.open and first.body / first.range >= 0.45
    doji_middle = is_doji(middle, maximum_body_ratio=maximum_doji_body_ratio)
    bearish_third = third.close < third.open and third.close <= (first.open + first.close) / 2
    star_located_high = min(middle.open, middle.close) >= min(first.open, first.close)
    return bullish_first and doji_middle and bearish_third and star_located_high


def evaluate_m5_confluence(
    *,
    price_action: bool,
    rsi: bool,
    stochastic: bool,
    bollinger: bool,
) -> ConfluenceResult:
    votes = sum((price_action, rsi, stochastic, bollinger))
    anchored = price_action or bollinger
    passed = votes >= 2 and anchored
    if passed:
        reason = "M5 confluence vote passed"
    elif votes < 2:
        reason = "fewer than two independent M5 confirmations"
    else:
        reason = "M5 confirmation lacks price-action or Bollinger evidence"
    return ConfluenceResult(passed, votes, reason)
