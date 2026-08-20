# G04 Pure Rule Extraction

Status: **IN_PROGRESS**

Scope: SHARED, GOLDI, GOLDM. No strategy parameter or signal threshold is tuned. REAL authority remains disabled.

## Extraction

The current Revised and Bear implementations were moved into `gold_engine_core.rules`:

- Revised engine and M5 setup detector;
- Bear M15 engine, candidate configs, and H1/M5/M1 multi-timeframe replay rules.

The former `goldm_revised` and `goldm_bear` modules are compatibility exports. Legacy replay, portfolio worker, and external imports now resolve to the exact same core class objects; there is no duplicate rule implementation.

Original audited Git blobs:

```text
1d80dc70fad5cb8146a7ce6beec54a1299a0b39f  src/goldm_revised/engine.py
b11d51b7a26bd5c36535ecacb46e7f051e301d4b  src/goldm_revised/setup.py
e75c5a53af20a5271cb4ba6997b7f7b77f70fe33  src/goldm_bear/engine.py
8911557283c6fcf9b59d83090d282b7870b6bfdf  src/goldm_bear/candidate.py
9a50aebe4149e7628534218dc2cb12e5b4f39504  src/goldm_bear/multitimeframe.py
```

Formatting, explicit coercion boundaries, sequence typing, and a loop-closure binding defect were corrected while preserving behavior. No global mypy suppression or ignored package is used.

## Purity and identity

- Core rule modules have no MT5, environment, DB, Telegram, network, sleep, or order-send imports/calls.
- Legacy Revised/Bear replay and portfolio worker objects are identical to core rule objects.
- Existing tick-driven ceiling/normalization behavior remains profile tick-size driven.
- G02 corpus rebuild remains byte-identical by retaining captured source-oracle fingerprints.

## Focused verification

```text
python -m ruff check <core rules, compatibility modules, extraction tests>
exit=0

python -m mypy --follow-imports=skip src/gold_engine_core/rules scripts/quality_gate.py
exit=0

python -m pytest -q <core + Revised/Bear focused tests>
exit=0
result=132 passed

core contracts coverage: 41 passed, 91.77%
core_coverage_xml_sha256=37fa85b745f5be458a2c0dd575a711708275d6e4785cc0249a6fe5009ef8ab89

extracted rules coverage: 91 passed, 77.22%
rule_coverage_xml_sha256=843fb9a0c45df34fe3fda30b49bccde30dbb632d83f503061d9adbc047e9921a
```

New contracts remain gated at 90%. Extracted legacy rules start with a fail-closed 75% branch-coverage ratchet; G12/G13 parity work must raise it rather than lower it.

Quality-gate E2E, corpus regeneration after commit, and full regression remain required before PASS.
