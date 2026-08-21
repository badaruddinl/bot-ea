# G15 Full Parity Certification

Status: **IN_PROGRESS**

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

REAL orders: **DISABLED**
