# GoldI MT5 safe bar backtest and internal OOS — 2026-08-17

## Decision

Keep the latest GitHub production baseline as `ALL`. Do not promote either
independent directional engine. The directional samples are far below the
registered minimum and BEAR loses its only internal-OOS outcome.

No real account was activated and no broker order was submitted. Every EA used
here is signal-only; the tester final balance remained USD 10,000.

## Registered data and isolation

- policy classification: `DEVELOPMENT_SELECTION`;
- development backtest: `[2022-02-28, 2022-12-01)`;
- internal confirmation OOS: `[2022-12-01, 2023-03-28)`;
- protected quarantine `[2026-02-28, 2026-07-01)` was not read or tested;
- custom alias: `GOLD_i_DEV_SAFE`;
- model: EPSOFT BID M5 bars stored as sparse M1 custom rates, MT5 model 1;
- dataset rows: 87,723, from `2021-01-01T05:00:00Z` through
  `2023-03-27T23:55:00Z`;
- dataset-manifest file SHA-256:
  `525e700873aaca5cce53c1045e0a05491e97707005989fc041999094df1326a4`;
- exported CSV SHA-256:
  `552053eef842ed3108db013c9a1bbb9119912cc16ed52d964746069877030f5a`;
- export-receipt file SHA-256:
  `1b195d0b03052abbca74daca1a41ce39c9630e4875d31c0b0c3a5980a13e7034`;
- isolated terminal: signed MetaTrader build `5.0.0.6090` under
  `C:\ProgramData\goldm-mt5-research-portable-6090`;
- live firewall evidence status: `ENFORCED_OFFLINE_VERIFIED`;
- firewall evidence file SHA-256:
  `9156228f95ac6fc810558a2ff44a7c2452a7d5faac5d2bea86b4924317d002f8`.

The account metadata selected login `108098316`, whose MT5 account scope was
logged as `demo`. Firewall logs consistently reported no connection to
`XMGlobal-MT5 5`. Global Algo Trading remained disabled. A temporary localhost
MetaTester service was removed after testing.

## Results

| Engine | Source identity | Split | Resolved | Stops | Hit 1R | Hit 2R | Total R | Expectancy R | OnTester |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| ALL baseline | HEAD `f1b2226`, strategy 1.72 | DEV | 8 | 5 | 3 | 1 | +0.36815 | +0.04602 | +0.0460189 |
| ALL baseline | HEAD `f1b2226`, strategy 1.72 | internal OOS | 1 | 0 | 1 | 1 | +1.71455 | +1.71455 | +1.7145532 |
| ALL donor parity | `cf8ab050`, strategy 1.73 | DEV | 8 | 5 | 3 | 1 | +0.36815 | +0.04602 | +0.0460189 |
| ALL donor parity | `cf8ab050`, strategy 1.73 | internal OOS | 1 | 0 | 1 | 1 | +1.71455 | +1.71455 | +1.7145532 |
| BULL independent | `BULL_ENGULF_RECLAIM@0.1.0`, `cf8ab050` | DEV | 2 | 1 | 1 | 0 | -0.84337 | -0.42169 | -0.4216867 |
| BULL independent | `BULL_ENGULF_RECLAIM@0.1.0`, `cf8ab050` | internal OOS | 0 | 0 | 0 | 0 | 0.00000 | 0.00000 | -999 |
| BEAR independent | `BEAR_SINGLE_REJECTION@0.1.0`, `cf8ab050` | DEV | 1 | 0 | 1 | 0 | -0.02581 | -0.02581 | -0.0258065 |
| BEAR independent | `BEAR_SINGLE_REJECTION@0.1.0`, `cf8ab050` | internal OOS | 1 | 1 | 0 | 0 | -1.00000 | -1.00000 | -1.0000000 |

The latest-ALL source SHA-256 was
`0c6290f0dad3f93b25388bf4bdd4929bb10b5dd9048a5f538a117f187585e16e`.
Its compiled EX5 SHA-256 was
`f16a505373e16602f0bcc7603f8422ef70509eb0d5072100bbf175d853d454d4`.
The correlated tester-agent log SHA-256 was
`41a2a8e58536a472ec08cc383ae3b83befa8211e29c549a31754468b37f8606e`.

## Interpretation

This is an exploratory bar-model confirmation, not a real-tick backtest. It has
no broker ask path, true spread path, commission, swap, slippage, or intrabar
tick ordering. Five-minute source bars are sparse within the M1 series.

The OOS label is **internal confirmation OOS**, not blind OOS: this registered
development dataset was already used by the directional research pipeline. The
single positive ALL OOS outcome is not statistically meaningful. BULL and BEAR
both fail sample gates; BEAR also fails sign/expectancy in OOS. No threshold or
algorithm was changed after observing these OOS rows.

Operational conclusion: preserve latest GitHub ALL unchanged, keep BULL/BEAR as
research-only candidates, and do not deploy either directional engine to demo
or real execution from this evidence.
