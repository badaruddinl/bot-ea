# G10 Reference Live DEMO Validation

Status: **IN_PROGRESS — ACTUAL DEMO PREREQUISITES MISSING**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. REAL authority remains disabled.

## Prepared safety contracts

- Canonical `GOLDI_DEMO_VALIDATION` manifest derived from the GOLDI fingerprint.
- Canonical `GOLDM_DEMO_VALIDATION` manifest derived from the unchanged GOLDM production fingerprint.
- GOLDM validation uses only `GOLDM_DEMO_*`; REAL env names/login cannot be reused.
- Both validation manifests require DEMO mode and set `production_real_authority=false`.
- GOLDM validation evidence is admin-only.
- Separate shadow and guarded-DEMO worker configs, state, audit, terminal, and account bindings exist per profile.
- Read-only terminal probe contains no order/check/send/position mutation API.
- Runbook defines shadow → guarded DEMO → position lifecycle → restart acceptance.

## Current prerequisite evidence

The sanitized preflight was executed on 2026-08-21 and returned `ready=false` with SHA-256:

`b0493d614333994cf0671cc70ea25f53f76916450b3230bd7c43b17c830e7e93`

Missing facts:

- GOLDI dedicated terminal path/login/server env;
- GOLDM safe-DEMO terminal path/login/server env;
- both dedicated terminal executables at those paths;
- MetaTrader5 Python module in the validation interpreter;
- therefore no actual terminal/account/symbol/tick/bar/latency evidence yet.

No credential value is present in the report. The standard MT5/MetaEditor build 6090 installation alone cannot substitute for two bound DEMO terminals.

## Prepared verification

```text
DEMO manifest/config/probe tests: 9 passed
new-core suite: 93 passed
new-core branch coverage: 91.27%
demo_validation.py coverage: 83%
core_coverage_xml_sha256=de20995062eda69b09866294e1ec17ba8572800391aa392a46345b1a53b273ef
production_real_orders=DISABLED
```

## Remaining PASS evidence

G10 cannot become PASS until actual evidence proves both profiles concurrently on separate DEMO terminals, shadow health, guarded DEMO entry, position/close lifecycle, restart recovery, no duplicate/state/privacy bleed, no live replay, measured latency, and continued GOLDM REAL disablement.

G11 and later gates must not begin before these prerequisites and G10 PASS are available.
