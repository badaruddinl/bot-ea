# G09 Causal Tick-Aware Replay

Status: **IN_PROGRESS**

Scope: SHARED, GOLDI, GOLDM. REAL authority remains disabled.

## Common runtime replay

`ReferenceRuntimeReplay` feeds the exact `ReferenceProfileRuntime` used by the incremental target. It does not call a separate backtest strategy implementation.

- monotonic ticks drive new-bar detection;
- bars are indexed by exact timeframe/open timestamp;
- a bar is dispatched only when its requested close time is no later than the current tick;
- absent bars and profile/fingerprint/symbol crossover fail closed;
- bars/ticks after `replay_end` are excluded;
- decisions earlier than `warmup_until` are counted but non-tradable;
- event hashes use profile-namespaced runtime event order.

M1/M5/M15/H1 durations are checked explicitly. D1 is supported by the same feeder. All timestamps require explicit broker offsets, independent from OS timezone.

## Intrabar resolution

When ticks exist, BUY outcomes use bid and SELL outcomes use ask in timestamp order, preserving spread. Without a post-entry tick path, a closed-bar fallback is allowed. If SL and TP are both touched by the same bar, STOP wins deterministically. No future price or unresolved outcome is invented.

## Separate deterministic reports

| Profile | Symbol | Closed bars | Ticks | Decisions | Warm-up suppressed | Event hash | Report SHA-256 |
|---|---|---:|---:|---:|---:|---|---|
| GOLDI | `GOLD.i#` | 4 | 2 | 4 | 4 | `9361ba19a8bdc596207733fd1abfd722477dc4e8569f0ede8c4440beaa46b04c` | `75dd1328624c31336dff42e0bf0fcc0d8dfe3a0f4df3ed4a83c75d3912e238d8` |
| GOLDM | `GOLDm#` | 4 | 2 | 4 | 4 | `3a0ed11ad35d46e6a05e8cac67b77e38940505dc3a5856abe1fc0a430e6c5c0f` | `e43f447f3ef89a4b9bf09a8c2ffcebff346f8b36339d6809646a2a182c70346d` |

The evidence builder reproduces both report files byte-identically.

## Focused verification

```text
causal/tick replay tests: 7 passed
ruff format/lint: PASS
mypy: PASS
new-core suite: 83 passed
new-core branch coverage: 91.87%
causal_replay.py coverage: 87%
core_coverage_xml_sha256=f9d752466ba78ed139c6240914d85f4f4a0f5f214199c293d85e136e395c139b
```

Quality-gate E2E and full regression remain required before G09 becomes PASS.
