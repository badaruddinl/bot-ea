# G12S Adaptive Balance-Tier Sizing Contract

Status: **PASS**

Scope: GOLDI, GOLDM, CROSS_PROFILE. This is an explicit user-authorized profile
contract amendment. REAL order authority remains disabled.

## GOLDI

\`\`\`text
<100       0.01
>=100      0.02
>=200      0.05
>=1000     0.10
>=2000     0.20
>=10000    1.00
>=20000    2.00
maximum_positions=2
maximum_total_lot=4.0
profile_version=1.1.0
profile_fingerprint=7af1d75e1be54ba4505b32cedcf53f4317dea0a90a2a0636510884d0d408c5b5
\`\`\`

## GOLDM

\`\`\`text
0-9.99       0.1
10-29.99     0.2
30-49.99     0.5
50-99.99     1.0
100-199.99   2.0
200-999.99   5.0
1000-1999.99 10.0
2000-9999.99 20.0
>=10000      100.0
maximum_positions=2
maximum_total_lot=200.0
profile_version=1.1.0
profile_fingerprint=704b383f959298c8a1b1dd5c21665ffb7a022dc9831c7498e68cc37f607d4c24
\`\`\`

The final GOLDM boundary is normalized to \`>=10000\` so balance exactly 10000
cannot fall through an undefined gap.

## Consistency and evidence regeneration

- engine manifests, final workers, and all validation workers carry identical
  tiers;
- Python and MQL5 use last-applicable ascending boundary semantics;
- per-position broker caps remain enforced by symbol metadata;
- exposure ceilings permit two maximum-tier positions;
- engine, execution, validation, current-behavior, causal replay, read-only
  probe, Revised parity corpus, embedded MQL5 fingerprint, and G11 compile
  evidence were regenerated;
- strategy/component hashes, symbol, magic, audience, and order-authority
  default did not change.

## Verification

\`\`\`text
focused_profile_and_runtime=115 passed
default_regression=658 passed, 154 deselected, 77 subtests passed
slow_release_regression=154 passed, 658 deselected, 64 subtests passed
quality_gate=PASS
core_coverage=90.12%
rule_coverage=82.66%
GOLDI_compile=0 errors, 0 warnings
GOLDM_compile=0 errors, 0 warnings
focused_junit_sha256=259b3b112491f4dd7cd395c5f4f0e22f8cc16649228add843128951be1efcfdc
slow_junit_sha256=b71ac8a914f96a55df66ec6ac592e0b86f0556bca82b1fe5db6bb396e51105ef
\`\`\`

REAL orders: **DISABLED**
