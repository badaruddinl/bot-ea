# G21 Final Release Evidence

Status: **PASS**

Production REAL order authority remains **DISABLED**.

Final release facts:

- GOLDI fresh-VM binary SHA-256:
  `b3142e26e37fdca846cdece3694dbfbb75d5bd201ea46f3c9835767ccc3bfd4c`;
- GOLDM fresh-VM binary SHA-256:
  `29aab8b4105d8b640161018913d6a6a0b15296ec182acc816e2dc06d89bce0f4`;
- source commit: `087314d49fbea11ec9b608935c19419fdb1a2b64`;
- both profile manifests equal the canonical source manifests and reproduce the
  certified fingerprints;
- all G00–G20 required matrix cells are PASS or contract-valid N/A;
- certification gates G10, G15, G17, G18, G19, and G20 are independently
  hashed and PASS;
- pre-G20 rollback binaries are packaged with G19-certified hashes;
- strict release verifier: PASS, zero violations, zero open P1;
- focused G21 tests: 4 PASS;
- final fast regression: 836 PASS, 154 deselected, 77 subtests PASS;
- final slow regression: 154 PASS, 836 deselected, 64 subtests PASS;
- incremental quality ratchet: Ruff/format PASS, core coverage `90.20%`,
  strategy-rule coverage `82.66%`, no changed production mypy source files;
- two known `TesterSettings` pytest collection warnings remain non-release
  blocking and are documented legacy debt.

Release tree: `release/`.

REAL orders: **DISABLED**
