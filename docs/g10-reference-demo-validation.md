# G10 Reference Market-Data and Execution Validation Runbook

This runbook cannot authorize REAL orders. GOLD.i uses its dedicated DEMO
binding. Because the broker does not offer a semantically equivalent GOLDm
DEMO contract, GOLDm uses `GOLDM_REAL_READ_ONLY` only for broker metadata,
ticks, spreads, and closed bars; execution evidence comes from isolated
Strategy Tester batches.

## Prerequisites

1. Two distinct MT5 installations/data directories are available simultaneously.
2. `GOLDI_MT5_*` resolves to a GOLD.i# DEMO account.
3. `GOLDM_REAL_MT5_*` resolves to the canonical GOLDm# account in read-only
   probe mode.
4. The GOLDm probe exposes no order/deal/position mutation API and records
   `orders_sent=0`.
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

## Guarded execution evidence

For GOLD.i, only after shadow review, start the dedicated DEMO process. An
executable signal must pass the G08 immutable plan and all broker guards.
Capture entry, broker response, position lifecycle, close, P/L, restart, and
latency.

For GOLDm, run the profile-locked binary in isolated Strategy Tester batches
using real ticks. Capture entry/close lifecycle, restart corpus, parity,
broker-constraint simulation, and latency. Never substitute a tester result for
a claim of live broker execution.

Do not enable REAL order authority, modify the production manifest, or run
Python and EA order authorities concurrently. The read-only GOLDm probe may
attach to the already authenticated production terminal only to read permitted
market/account metadata.

## Acceptance

G10A remains non-PASS until actual read-only market-data evidence exists for
both profiles with no state/privacy bleed and explicit
`production_real_orders=DISABLED`. G10B requires the GOLD.i DEMO lifecycle.
G10C is completed after G15 and requires GOLDm Strategy Tester batch evidence,
restart recovery, no duplicates, parity, and an explicit proof that no live
order API ran.

Run the fail-closed verifier against the external evidence directory:

```powershell
python scripts/verify_g10_demo_evidence.py --evidence-root <external-evidence> --output <external-evidence>\acceptance.json
```

Only `accepted=true` with a non-null evidence fingerprint permits closing G10.
