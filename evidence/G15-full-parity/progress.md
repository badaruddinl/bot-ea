# G15 Full Parity Certification

Status: **PASS**

Locked scope:

- compare Python replay, Python incremental, MQL5 harness, and MT5 Strategy
  Tester without tuning strategy parameters;
- certify exact profile, event/setup identity, version, state, side, reason,
  semantic time, and management action;
- require planned entry/SL/TP differences to remain within one profile tick;
- prove GOLDI/GOLDM and cross-profile isolation;
- treat equity as supplementary evidence only;
- keep production REAL order authority **DISABLED**.

Current sub-batch:

- G12 Revised parity, G13 Bear parity, and G14 execution/lifecycle evidence are
  frozen as inputs;
- building one canonical certification manifest and verifier that rejects
  incomplete profile/pipeline/field coverage or cross-profile events.
- canonical certification PASS across both profiles and all four pipelines;
  exact field coverage, zero cross-profile events, zero observed price-tick
  delta, and disabled REAL authority are hash-locked.
- verifier exposed and corrected a stale G12 evidence pointer to the already
  regenerated Revised sizing corpus; strategy/corpus bytes were not changed.
- thin GOLDI/GOLDM lifecycle harnesses now share one core. GOLDM engineering
  mode is allowed only when profile is GOLDM, the plan explicitly opts in, and
  `MQLInfoInteger(MQL_TESTER)` is true.
- isolated lifecycle Strategy Tester PASS on GOLDI and GOLDM: open, ownership
  discovery, modify, reconstructed-broker restart recovery, and close; all
  mutation retcodes `10009`, positions `0 -> 0`, and `OnTester result 1`.
- final MetaEditor compile: two profile EAs and two lifecycle harnesses all 0
  errors and 0 warnings.
- full regression PASS: 805 fast and 218 slow tests.
- quality gate PASS: Ruff, 90.12% safety-core coverage, and 82.66% changed-rule
  coverage.

Final certification:

- exact event parity for GOLDI and GOLDM;
- price delta within one tick (observed zero);
- no cross-profile event or authority bleed;
- externally checksummed raw tester, compile, binary, and JUnit evidence.

REAL orders: **DISABLED**
