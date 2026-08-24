# G21 Certification Summary

The `v1.1.0` dual-profile release is complete and profile locked. The packaged
binaries are byte-identical to the G20 fresh-VM binaries. `SHA256SUMS.txt`
covers every release artifact except itself, and the strict verifier checks the
file set, hashes, binary provenance, manifests, profile fingerprints, upstream
certifications, ledger, and disabled REAL authority.

GOLDI remains DEMO. GOLDM remains REAL read-only for broker-data validation and
Strategy Tester only for engineering execution. Enabling REAL orders is not a
release operation and remains human-controlled.

Certification: `certification.json`.

REAL orders: **DISABLED**
