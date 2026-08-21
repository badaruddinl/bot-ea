from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ORACLE = REPOSITORY_ROOT / "corpus" / "bear_parity" / "m15_scanner_oracle.json"


def render_fixture() -> str:
    payload = json.loads(ORACLE.read_text(encoding="utf-8"))
    vectors = payload["vectors"]
    if len(vectors) != 2:
        raise ValueError("M15 oracle must contain exactly two profiles")
    left = [
        {key: value for key, value in item.items() if key != "spread"}
        for item in vectors[0]["bars"]
    ]
    right = [
        {key: value for key, value in item.items() if key != "spread"}
        for item in vectors[1]["bars"]
    ]
    if left != right:
        raise ValueError("GOLDI/GOLDM M15 oracle OHLC inputs differ")
    lines = [
        "#ifndef G13_BEAR_M15_ORACLE_MQH",
        "#define G13_BEAR_M15_ORACLE_MQH",
        "",
        "void BuildG13BearM15Oracle(EngineBar &bars[],const int spread_points)",
        "  {",
        f"   ArrayResize(bars,{len(left)});",
    ]
    for index, item in enumerate(left):
        timestamp = datetime.fromisoformat(item["time"]).strftime("%Y.%m.%d %H:%M:%S")
        lines.extend(
            (
                "   SetBearHarnessBar(",
                f"      bars[{index}],PERIOD_M15,D'{timestamp}',",
                f"      {item['open']:.10f},{item['high']:.10f},",
                f"      {item['low']:.10f},{item['close']:.10f},{index});",
                f"   bars[{index}].spread_points=spread_points;",
            )
        )
    lines.extend(("  }", "", "#endif", ""))
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic G13 M15 MQL5 fixture")
    parser.add_argument(
        "--output",
        type=Path,
        default=(
            REPOSITORY_ROOT / "mt5" / "Experts" / "bot-ea" / "fixtures" / "G13BearM15Oracle.mqh"
        ),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render_fixture(), encoding="utf-8", newline="\n")
    print(f"bars=50 output={args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
