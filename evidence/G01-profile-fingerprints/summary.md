# G01 Dual-Profile Fingerprints

Status: **IN_PROGRESS**

Scope: GOLDI, GOLDM, CROSS_PROFILE. REAL order authority remains disabled.

## Canonical manifests

| Profile | Manifest | Canonical SHA-256 |
|---|---|---|
| GOLDI | `config/engine_profiles/GOLDI.json` | `23598f01c472aebafd36cb15358178d40b76fab382cd0487ba3158c8421ead64` |
| GOLDM | `config/engine_profiles/GOLDM.json` | `c2e513cb100da86c814d9d65566c835da96f3ea1fd79d35602f2c34fd7b6dac6` |

The manifests are strict, immutable typed contracts. Unknown keys, non-canonical values, checksum mismatch, component hash swap, cross-profile symbol/magic/path/audience reuse, unsafe relative paths, and invalid runtime identity fail closed.

GOLDM records its production identity as REAL but sets `order_authority_default=disabled`; engineering DEMO acceptance requires an explicit call-site flag and does not authorize orders.

## Focused verification

```text
python -m ruff format --check src/gold_engine_core tests/gold_engine_core
exit=0

python -m ruff check src/gold_engine_core tests/gold_engine_core
exit=0

python -m mypy --follow-imports=skip src/gold_engine_core
exit=0

python -m pytest -q --basetemp=<external>/G01-profile-fingerprints/pytest-temp-run3 --cov=gold_engine_core --cov-branch --cov-report=term-missing --cov-report=xml:<external>/G01-profile-fingerprints/coverage-run3.xml --cov-fail-under=90 tests/gold_engine_core
exit=0
result=16 passed
branch_coverage=98.02%
coverage_xml_sha256=ad9f7870e035c332cbd8d959e9a8796bb1ce7ad79eede664638516daf47873de
```

The preceding run exposed and then verified a fix for non-finite Decimal validation order. Quality-gate E2E and full regression remain pending before G01 can be marked PASS.
