# G00 Environment

Captured on 2026-08-20 in `SE Asia Standard Time`.

## Host and tooling

- Windows 11 Pro `10.0.26200`, build `26200`, 64-bit.
- Python `3.12.10`; pytest version and executable are retained in raw environment evidence.
- WSL distributions observed: Ubuntu (WSL2), Ubuntu-22.04 (WSL2), Ubuntu-RTK-WSL1, and docker-desktop.
- MT5 terminal: `C:\Program Files\MetaTrader 5\terminal64.exe`, build `5.0.0.6090`.
- MetaEditor: `C:\Program Files\MetaTrader 5\MetaEditor64.exe`, build `5.0.0.6090`.
- No MT5 process was running during G00 capture.
- Dedicated GOLD.i and GOLDm terminal path environment bindings were not present on this host at capture time.

## Profile metadata recorded from the exact baseline

| Field | GOLD.i | GOLDm |
|---|---|---|
| Symbol | `GOLD.i#` | `GOLDm#` |
| Intended baseline mode | DEMO | REAL |
| Magic | `26081911` | `26081912` |
| Audience | approved subscribers | admin-only |
| Worker first boot | OFF | OFF |

The baseline GOLDm portfolio declares REAL mode and `orders_enabled=true`. G00 did not start the orchestrator, terminal, worker, or order executor. Goal engineering keeps REAL authority disabled and requires a safe GOLDm DEMO mirror for E2E.

Broker-exported runtime symbol metadata is not available in this capture because the dedicated terminals were not running/bound. User-supplied instrument specifications remain contextual input, not broker-exported G00 evidence.

## Raw evidence hashes

- `environment.json`: `7ac7739ad1be746d464717ddf3d69481f7244e7927c7b88f2567b87f565e74f9`
- `pip-freeze.txt`: `ae1ef1add8c969316269381454b923b96d1dade3257672d71f64d192672b61c8`
- `source-hashes.csv`: `8103bf8efe822b007db0c667456f247c390fe817820aef86c6985d6d65d71710`
