# G10 Reference DEMO Validation Runbook

This runbook cannot authorize a REAL account. GOLDM validation must use the dedicated `GOLDM_DEMO_*` bindings and `GOLDM_DEMO_VALIDATION` manifest.

## Prerequisites

1. Two distinct MT5 installations/data directories are available simultaneously.
2. `GOLDI_MT5_*` resolves to a GOLD.i# DEMO account.
3. `GOLDM_DEMO_MT5_*` resolves to a different GOLDm# DEMO account.
4. No GOLDM DEMO env value reuses a `GOLDM_REAL_*` binding or login.
5. MetaTrader5 Python integration is installed in the validation interpreter.

Run the sanitized preflight:

```powershell
python scripts/check_g10_demo_prerequisites.py
```

It must return `ready=true`. No value or credential is printed or stored.

## Read-only profile probe

Run each profile in a separate process while both dedicated terminals are open:

```powershell
python scripts/run_g10_profile_probe.py --profile GOLDI --output <external-evidence>\goldi-probe.json
python scripts/run_g10_profile_probe.py --profile GOLDM --output <external-evidence>\goldm-probe.json
```

The probe performs no order/check/send/position mutation and records sanitized terminal, symbol, closed-bar, tick, and latency evidence.

## Shadow stage

Start both workers independently with `--dry-run --no-telegram` and their `worker-shadow.json` files. Retain state, health, and audit artifacts. Confirm no replay call, duplicate event, state bleed, or cross-profile path.

## Guarded DEMO execution

Only after shadow review, start the `worker-demo.json` profile in its dedicated DEMO process. An executable signal must pass the G08 immutable plan and all broker guards. Capture entry, broker response, position lifecycle, close, P/L, restart, and latency.

Do not substitute production GOLDM, enable a REAL login, modify the production manifest, or run Python and EA order authorities concurrently.

## Acceptance

G10 remains non-PASS until actual evidence contains both profiles running concurrently, a guarded DEMO lifecycle, restart recovery, no duplicates/state/privacy bleed, latency, and an explicit `production_real_orders=DISABLED` record.

Run the fail-closed verifier against the external evidence directory:

```powershell
python scripts/verify_g10_demo_evidence.py --evidence-root <external-evidence> --output <external-evidence>\acceptance.json
```

Only `accepted=true` with a non-null evidence fingerprint permits closing G10.
