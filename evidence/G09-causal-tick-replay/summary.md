# G09 Causal Tick-Aware Replay

Status: **PASS**

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
| GOLDI | `GOLD.i#` | 4 | 2 | 4 | 4 | `9361ba19a8bdc596207733fd1abfd722477dc4e8569f0ede8c4440beaa46b04c` | `5292a8b21047812db8d7d4ba2f0ff7dd0417ff0c61ba3ab06f5e423cb82426f6` |
| GOLDM | `GOLDm#` | 4 | 2 | 4 | 4 | `3a0ed11ad35d46e6a05e8cac67b77e38940505dc3a5856abe1fc0a430e6c5c0f` | `0218dbb0c0ba48920cca34cd688c6f12056b0697792ea0f76ab1078542c9c617` |

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

## Final verification

```text
python scripts/quality_gate.py --base 5dd77b079612f8296dd54cb5012c6ceadc77b1bd --head HEAD
exit=0
quality_python_files=5
ruff_format=PASS
ruff_lint=PASS
mypy=PASS (2 changed source files)
causal_replay_core=84 passed, 91.87%
rule_and_restart_suite=106 passed, 82.66%

python -m pytest -q --basetemp=<external>/G09-causal-tick-replay/full-pytest-temp --junitxml=<external>/G09-causal-tick-replay/full-pytest-junit.xml
exit=0
result=809 passed, 2 warnings, 141 subtests passed
junit_tests=950
junit_failures=0
junit_errors=0
junit_skipped=0
junit_sha256=d97f17bec81f1af716b2769c61a90b0e817be1523d53c60cd94964946949e0a0
```

No terminal, broker account, or order API was used. The production REAL profile remained disabled throughout G09.
