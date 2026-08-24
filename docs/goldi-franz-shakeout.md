# GOLDI_FRANZ_SHAKEOUT 0.1.0

`GOLDI_FRANZ_SHAKEOUT` is a standalone, Strategy-Tester-only EA for
`GOLD.i#`. It does not import or modify Revised, Bear, GoldMSniperParity, their
profile manifests, state, magic, or release binaries.

## Rule provenance

Only the guest trader's method is represented. The forced mid-range entries
demonstrated by the host are explicitly excluded.

Derived podcast rules:

- naked-chart method and timeframe hierarchy:
  <https://www.youtube.com/watch?v=wZiTtPh7vho&t=633s>;
- do not counter the first large terminal wick:
  <https://www.youtube.com/watch?v=wZiTtPh7vho&t=1508s>;
- wait for repeated shakeout and the failed final push:
  <https://www.youtube.com/watch?v=wZiTtPh7vho&t=1803s>;
- distinguish trending Sniper from ranging Handgun:
  <https://www.youtube.com/watch?v=cjESyO-ACgs&t=321s>;
- never enter in the middle of an unclear range:
  <https://www.youtube.com/watch?v=cjESyO-ACgs&t=724s>;
- BUY only after a deep fall and lower shakeout; SELL only after a high rise
  and upper shakeout:
  <https://www.youtube.com/watch?v=cjESyO-ACgs&t=1521s>.

The repository stores these paraphrased rules and timestamps, not the raw
transcripts.

Research basis for the objective zone conversion:

- local minima/maxima and interval-based SR zones, bounce/penetration, bounce
  memory, and time decay: <https://arxiv.org/abs/2101.07410>;
- order clustering and acceleration after support/resistance breaks:
  <https://www.newyorkfed.org/research/staff_reports/sr125.html>;
- causal upper/lower fractal buffers:
  <https://www.mql5.com/en/docs/indicators/ifractals>.

## Objective implementation

- `SNIPER_TREND`: D1, H4, and H1 confirmed swing structures must align with
  the reversal side.
- `HANDGUN_RANGE`: Sniper is inactive and the 12-bar H1 efficiency ratio is
  at most `0.35`.
- M15 impulse: 3–8 closed bars, displacement at least twice the median true
  range, directional body share at least 65%, average overlap at most 35%.
- M1 shakeout: 4–12 closed bars, three direction changes, two distinct
  touches, an intervening excursion, and a liquidity sweep.
- Two M15 context trendline zones are mandatory: a bull-support line from
  confirmed pivot lows and a bear-resistance line from confirmed pivot highs.
  Each line needs at least two causal anchors. The first closed-M5 trendline
  break creates a watch; it never creates an entry by itself.
- Trendline-break and shakeout evidence are independently latched. Either may
  appear first; `BREAK_ATTEMPT` starts only after both exist inside the bounded
  setup window.
- Extreme watch lasts at most 60 M1 bars; after the M5 break sign, shakeout
  watch lasts at most 30 M1 bars. The actual cluster remains bounded to the
  latest 4–12 closed M1 bars.
- Confirmed M15/M30 swing supply/demand zones use a 2×2 pivot, 1–4 overlapping
  base candles, and a three-bar displacement departure. SELL must originate
  inside a supply zone; BUY must originate inside a demand zone.
- Supply/demand boundaries are intervals: distal is the extreme wick, proximal
  is the nearest base-body boundary. Zones merge only when overlapping or
  separated by at most 0.25 median range, expire after 240 M15 bars, and are
  invalidated by two consecutive or three-of-four closes beyond distal.
- RSI7 M1 and RSI14 M5 provide two of three required votes.
- Stochastic `(5,3,3)` can replace only the second re-entry close after an
  already proven sweep; it cannot replace micro-break, RSI, or Fibonacci.
- Fibonacci anchors lock at failed-break confirmation and never redraw.
- Fibonacci `B` is the active swing-zone distal boundary. The liquidity sweep
  wick remains separate and can push the structural SL farther away; this
  prevents a sweep outside the zone from shifting the entry geometry outside
  the zone itself.
- The initial micro-trendline break opens the watch. A sweep and failed break
  at the swing-zone distal boundary confirms the reversal. Entry then requires
  price to remain/retest inside the active supply/demand zone at Fibonacci
  progress 0–14.6%. The 23.6% level measures subsequent progress rather than
  forcing price to leave the zone and return. This keeps the 113% stop and 50%
  Handgun target compatible with the minimum 1.25R gate.

Handgun opens one `0.01` ticket. Sniper opens two `0.01` tickets with common
entry/SL and separate TP1/TP2. If the second ticket cannot be created, the
first is immediately closed. Magic `26081914` and `FRZ|...|T1/T2` comments
isolate ownership.

## Safety

The EA refuses `OnInit()` outside Strategy Tester. It validates `GOLD.i#`,
contract size 100, tick size `0.01`, min/step lot `0.01`, max lot 50, hedging
mode, and tester leverage `1:1000`.

Additional limits:

- maximum spread `0.60`;
- maximum three setups per server-day;
- 60-minute cooldown;
- daily lock at `-2R` or `+3R`;
- planned loss at most `min(10% equity, equity - $4)`;
- no mutation of positions outside symbol + magic + comment ownership.

## Reproducible tester command

Use the dedicated, stopped GOLD.i engineering terminal:

```powershell
.\scripts\run-goldi-franz-backtests.ps1 `
  -TerminalRoot "C:\path\to\isolated-goldi-terminal" `
  -AccountLogin 123456789 `
  -AccountServer "Broker-MT5 Server" `
  -EvidenceRoot "C:\evidence\goldi-franz" `
  -Suite Smoke `
  -BalanceCsv "100" `
  -VariantCsv "FULL" `
  -BatchId "smoke-001"
```

Attribution variants are `PRICE_ONLY`, `NO_STOCH`, and `NO_FIB_GATE`. Only
`FULL` can become a release candidate. Each run uses a unique state/audit
namespace, real ticks, variable spread, and 100 ms execution delay.

No script in this package attaches the EA to a chart, enables DEMO forward
execution, sends Telegram messages, or activates REAL authority.
