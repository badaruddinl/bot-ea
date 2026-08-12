from __future__ import annotations

from dataclasses import dataclass


FIBONACCI_RETRACEMENTS = (0.236, 0.382, 0.500, 0.618, 0.786)
FIBONACCI_EXTENSIONS = (1.272, 1.618, 2.000)


@dataclass(frozen=True, slots=True)
class FibonacciProjection:
    aligned: bool
    retracement: float
    nearest_level: float
    extensions: tuple[float, ...]


def evaluate_fibonacci_projection(
    *,
    side: str,
    impulse_start: float,
    impulse_end: float,
    price: float,
    tolerance: float = 0.06,
) -> FibonacciProjection:
    direction = side.strip().upper()
    if direction == "BUY":
        impulse_range = impulse_end - impulse_start
        retracement = (impulse_end - price) / impulse_range if impulse_range > 0 else float("nan")
        extensions = tuple(impulse_start + level * impulse_range for level in FIBONACCI_EXTENSIONS)
    elif direction == "SELL":
        impulse_range = impulse_start - impulse_end
        retracement = (price - impulse_end) / impulse_range if impulse_range > 0 else float("nan")
        extensions = tuple(impulse_start - level * impulse_range for level in FIBONACCI_EXTENSIONS)
    else:
        raise ValueError("side must be BUY or SELL")
    if impulse_range <= 0:
        raise ValueError("impulse start and end are not ordered for the selected side")
    if not 0 < tolerance < 0.20:
        raise ValueError("tolerance must be between zero and 0.20")

    nearest = min(FIBONACCI_RETRACEMENTS, key=lambda level: abs(retracement - level))
    return FibonacciProjection(
        aligned=abs(retracement - nearest) <= tolerance,
        retracement=retracement,
        nearest_level=nearest,
        extensions=extensions,
    )
