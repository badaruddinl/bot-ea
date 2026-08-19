from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "data" / "research" / "goldm_revised" / "replay_2020_2026.json"


def metrics(items: list[dict[str, object]]) -> dict[str, object]:
    total = sum(float(item["outcome_r"]) for item in items)
    return {
        "signals": len(items),
        "total_r": round(total, 6),
        "expectancy_r": round(total / len(items), 6) if items else 0.0,
        "targets": sum(item["result"] == "TARGET" for item in items),
        "stops": sum(item["result"] == "STOP" for item in items),
    }


def bucket(value: float, limits: tuple[float, ...]) -> str:
    previous = "MIN"
    for limit in limits:
        if value < limit:
            return f"{previous}_TO_{limit:g}"
        previous = f"{limit:g}"
    return f"GE_{limits[-1]:g}"


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    outcomes = report["outcomes"]
    dimensions = {
        "sma20": lambda item: (
            "ABOVE" if item["market_regime"]["above_h1_sma20"] else "BELOW"
        ),
        "h1_trend_atr": lambda item: bucket(
            float(item["market_regime"]["h1_trend_atr"]), (-2.0, 0.0, 2.0)
        ),
        "h1_efficiency": lambda item: bucket(
            float(item["market_regime"]["h1_efficiency"]), (0.2, 0.4)
        ),
        "m5_atr_expansion": lambda item: bucket(
            float(item["market_regime"]["m5_atr_expansion"]),
            (0.8, 1.0, 1.2),
        ),
        "supply": lambda item: (
            item["supply_zone"]["kind"] if item.get("supply_zone") else "NONE"
        ),
        "demand": lambda item: (
            item["demand_zone"]["kind"] if item.get("demand_zone") else "NONE"
        ),
    }
    output: dict[str, object] = {}
    periods = {
        "TRAIN_2020_2024": [
            item for item in outcomes if item["opened_at"][:10] <= "2024-12-31"
        ],
        "OOS_2025_2026": [
            item for item in outcomes if item["opened_at"][:10] >= "2025-01-01"
        ],
    }
    for dimension, selector in dimensions.items():
        rows: dict[str, dict[str, list[dict[str, object]]]] = {}
        for period, items in periods.items():
            grouped: defaultdict[str, list[dict[str, object]]] = defaultdict(list)
            for item in items:
                grouped[str(selector(item))].append(item)
            rows[period] = {
                key: metrics(values) for key, values in sorted(grouped.items())
            }
        output[dimension] = rows
    def e2_base(item: dict[str, object]) -> bool:
        supply = item.get("supply_zone") or {}
        regime = item["market_regime"]
        return bool(
            supply.get("kind") == "H1_SUPPLY_INSIDE"
            and regime["above_h1_sma20"]
        )

    e2_stages = {
        "A_H1_INSIDE_ABOVE_SMA": e2_base,
        "B_PLUS_TREND_0_TO_2": lambda item: e2_base(item)
        and 0 <= float(item["market_regime"]["h1_trend_atr"]) < 2,
        "C_PLUS_EFF_LT_0.2": lambda item: e2_base(item)
        and 0 <= float(item["market_regime"]["h1_trend_atr"]) < 2
        and float(item["market_regime"]["h1_efficiency"]) < 0.2,
        "D_PLUS_ATR_EXP_GE_1.2": lambda item: e2_base(item)
        and 0 <= float(item["market_regime"]["h1_trend_atr"]) < 2
        and float(item["market_regime"]["h1_efficiency"]) < 0.2
        and float(item["market_regime"]["m5_atr_expansion"]) >= 1.2,
        "E_PLUS_BULL_ENGULFING": lambda item: e2_base(item)
        and 0 <= float(item["market_regime"]["h1_trend_atr"]) < 2
        and float(item["market_regime"]["h1_efficiency"]) < 0.2
        and float(item["market_regime"]["m5_atr_expansion"]) >= 1.2
        and item["m5_pattern"] == "BULL_ENGULFING",
        "F_PLUS_RETEST_1": lambda item: e2_base(item)
        and 0 <= float(item["market_regime"]["h1_trend_atr"]) < 2
        and float(item["market_regime"]["h1_efficiency"]) < 0.2
        and float(item["market_regime"]["m5_atr_expansion"]) >= 1.2
        and item["m5_pattern"] == "BULL_ENGULFING"
        and item["retest_count"] == 1,
    }
    output["e2_like"] = {
        stage: {
            period: metrics([item for item in items if predicate(item)])
            for period, items in periods.items()
        }
        for stage, predicate in e2_stages.items()
    }
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
