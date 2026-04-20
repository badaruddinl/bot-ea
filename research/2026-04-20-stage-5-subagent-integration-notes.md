# Stage 5 Research: Subagent Integration Notes

Date: 2026-04-20  
Goal: integrate the latest parallel subagent findings into the repo while implementation continues without MT5 installed.

## 1. MT5 adapter and mock boundary

Subagent conclusion:

- the core bot should not depend directly on MT5 imports
- mock and real MT5 adapters should share the same interface boundary
- session, order capability, and execution constraints should be represented as snapshots, not scattered implicit checks

Implication for this repo:

- keep `src/bot_ea/mt5_adapter.py` as the integration seam
- keep `src/bot_ea/mt5_snapshots.py` as the normalization layer
- keep the project runnable without MT5 installed

## 2. Session breakout remains the best narrow baseline

Subagent conclusion:

- a narrow session-breakout family is the cleanest v1 baseline
- it should remain session-aware, spread-guarded, and news-guarded
- it should stand down aggressively rather than force low-quality breakouts

Implication for this repo:

- keep the first strategy closed-bar only
- do not widen the family into a multi-pattern discretionary engine yet

## 3. Validation harness should be artifact-driven

Subagent conclusion:

- validation should be MT5-agnostic
- trade, signal, fill, and cost artifacts should be separated
- portability across hosts matters, so summaries and manifests should be explicit and reproducible

Implication for this repo:

- maintain a validation layer that can summarize trade-level records without needing terminal access
- prefer portable artifacts and markdown/json summaries

## 4. Extra official MT5 notes worth carrying forward

Additional officially grounded notes from the latest subagent pass:

- `SymbolIsSynchronized()` is a useful preflight check before trusting symbol data
- custom symbols are a later good option for replay and edge-case testing inside MT5
- `Math calculations` test mode is useful for pure formula checks, but not execution realism
- Python integration remains terminal-dependent and polling-based, not event-driven like a full EA

## 5. Bottom line

The repo is still aligned with the strongest evidence:

- risk-first
- session-aware
- MT5-aware but not MT5-dependent during scaffold stage
- validation-conscious
- skeptical of standalone candlestick alpha
