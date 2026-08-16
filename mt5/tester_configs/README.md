# Disabled legacy tester configurations

The two historical `GoldMHighRiskMicroScalper` tester INI files were removed
because their executable date ranges overlapped the protected quarantine
`[2026-02-28, 2026-07-01)`. They must not be recreated, launched, or used as
fixtures.

All future GOLDM tester configurations are generated per immutable run by
`scripts/run-goldm-research-safe.py` only after the Python policy guard,
bounded-offline dataset evidence, exact terminal isolation, compilation,
broker-cost provenance, and append-only registry checks pass. Generated INI
files belong in a run artifact directory and are never committed here.
