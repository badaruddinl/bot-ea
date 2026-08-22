# GOLD.i Portable Account and Instrument Binding SOP

## Status and scope

This document defines the target provisioning and deployment contract for a
portable `GOLDI` engine. It is an implementation specification and operator
SOP; it does not by itself enable orders or change the certified G21 binaries.

The operational end-to-end deployment procedure, including the optional
multi-account topology, is defined in
[`goldi-portable-e2e-deployment-sop.md`](goldi-portable-e2e-deployment-sop.md).

The scope is `GOLDI` only. `GOLDM`, its `GOLDm#` symbol, sizing, account,
terminal, magic, state, and admin-only notification route remain unchanged and
must not use this workflow.

The objective is to reuse the certified GOLD.i strategy on another compatible
gold symbol or account without editing strategy code. Portability means that
the deployment discovers broker properties and creates an explicit immutable
binding. It does not mean that the EA may silently follow an account or symbol
change.

## Safety boundary

- A new binding always starts with order authority disabled.
- The EA never logs in to an account and never stores an MT5 password.
- A chart symbol, login, server, trade mode, or leverage change invalidates the
  active binding and stops new orders.
- Symbol aliases are never guessed. The exact chart symbol must be recorded.
- A `0.01` minimum lot alone does not prove GOLD.i compatibility.
- DEMO-to-REAL promotion creates a new deployment binding. It never mutates a
  running DEMO binding in place.
- REAL activation remains a separate, explicit human action after all
  preflight checks pass.
- Existing positions are managed only by the exact account, symbol, magic, and
  deployment identity that opened them.

## Configuration layers

The portable design separates three concerns.

### Strategy profile

The strategy profile remains certified and immutable:

- profile family: `GOLDI`;
- Revised and Bear rule hashes;
- timeframe and causal closed-bar behavior;
- entry, invalidation, SL, TP, and management rules;
- GOLD.i balance-to-lot tiers;
- strategy version and release binary hash.

Changing one of these fields is a strategy release, not account provisioning.

### Instrument binding

The instrument binding records both approved expectations and the values read
from MT5. Discovery must collect at least:

- exact symbol name and description;
- base/profit/margin currencies;
- digits, point, and trade tick size;
- contract size;
- tick value, tick value profit, and tick value loss;
- minimum, maximum, and step volume;
- stop and freeze levels;
- trade and order modes;
- supported filling modes;
- quotes and trade-session availability;
- current spread and the configured maximum spread;
- margin required for every candidate order through `OrderCalcMargin` and
  `OrderCheck`.

The approved default GOLD.i economic contract is:

| Property | Required initial value |
|---|---:|
| Asset | Gold / XAUUSD-equivalent |
| Contract size | 100 troy ounces per lot |
| Minimum volume | `0.01` lot or lower |
| Volume step | `0.01` lot or lower |
| Price tick size | `0.01` USD |
| Profit currency | USD |

Any difference in contract size, tick economics, or profit currency requires a
new sizing certification. The provisioner must fail closed rather than scale
the lot by assumption. In particular, the `GOLDM` one-ounce contract is not a
compatible GOLD.i alias even though it also represents gold.

### Account and deployment binding

Each installed instance must bind:

- deployment ID;
- exact MT5 login and server;
- account trade mode (`DEMO` or `REAL`);
- observed and approved leverage;
- exact terminal executable and data directory;
- exact chart symbol and instrument fingerprint;
- GOLD.i magic number;
- binary and strategy fingerprints;
- dedicated state, spool, audit, and log namespaces;
- notification audience;
- order-authority state and the human activation receipt.

The deployment ID must change when login, server, trade mode, leverage,
instrument fingerprint, or terminal identity changes. State from another
deployment must not be reused.

## Leverage contract

Leverage is an account property controlled by the broker. MQL5 can read
`ACCOUNT_LEVERAGE`, but an EA cannot safely set or change it. A leverage change
must be performed through the broker's account controls and then followed by a
new discovery and binding cycle.

For the currently described GOLD.i account, the initial approved expectation
is `1:1000`. Provisioning records this as:

```json
{
  "leverage": {
    "source": "ACCOUNT_LEVERAGE",
    "approved": 1000,
    "mismatch_action": "DISABLE_ORDER_AUTHORITY",
    "automatic_lot_multiplier": false
  }
}
```

Leverage affects required margin, not the planned price loss at SL. The engine
must never increase a lot because leverage is higher. A lower or different
leverage may be supported only after it is explicitly approved and the broker
margin preflight passes for the selected lot. The checks immediately before an
order remain authoritative:

1. read the current leverage again;
2. require equality with the approved binding;
3. calculate required margin using the live symbol and quote;
4. run `OrderCheck`;
5. reject if free margin or any broker constraint is insufficient.

## GOLD.i lot schedule

The current GOLD.i balance schedule remains:

| Balance in USD | Lot |
|---:|---:|
| `< 100` | `0.01` |
| `>= 100` and `< 200` | `0.02` |
| `>= 200` and `< 1,000` | `0.05` |
| `>= 1,000` and `< 2,000` | `0.10` |
| `>= 2,000` and `< 10,000` | `0.20` |
| `>= 10,000` and `< 20,000` | `1.00` |
| `>= 20,000` | `2.00` |

This table may be used only when the instrument passes the certified 100-ounce
economic contract. The selected lot must still be normalized down to the
broker volume step and remain within volume, exposure, and margin limits. If
the broker minimum exceeds the tier lot, the trade is rejected; the lot is not
rounded up.

The balance is read immediately before creating the signal plan and checked
again before submission. A signal plan freezes its volume; a later balance
change does not enlarge an already prepared order.

## Target binding document

The provisioner should produce canonical JSON equivalent to the following
shape. Secret values are prohibited.

```json
{
  "schema_version": 1,
  "profile_family": "GOLDI",
  "deployment_id": "goldi-<server>-<login>-<symbol>-<revision>",
  "binary_sha256": "<64-lowercase-hex>",
  "strategy_fingerprint": "<64-lowercase-hex>",
  "account": {
    "login": 12345678,
    "server": "Broker-MT5 Demo",
    "trade_mode": "DEMO",
    "leverage": 1000
  },
  "terminal": {
    "identity": "<dedicated-terminal-id>",
    "executable": "<approved-absolute-path>",
    "data_directory": "<approved-absolute-path>"
  },
  "instrument": {
    "symbol": "<exact-chart-symbol>",
    "contract_size": "100",
    "tick_size": "0.01",
    "tick_value_profit": "<observed>",
    "tick_value_loss": "<observed>",
    "volume_min": "0.01",
    "volume_max": "<observed>",
    "volume_step": "0.01",
    "profit_currency": "USD",
    "margin_currency": "USD",
    "fingerprint": "<canonical-instrument-sha256>"
  },
  "ownership": {
    "magic": 26081911,
    "state_namespace": "runtime_data/goldi/<deployment-id>/state",
    "spool_namespace": "runtime_data/goldi/<deployment-id>/spool",
    "audience": "goldi_approved"
  },
  "authority": {
    "orders_enabled": false,
    "activated_by": null,
    "activated_at": null
  }
}
```

Canonical serialization and a SHA-256 fingerprint bind the entire document.
The EA receives the expected fingerprint separately and refuses a modified or
wrong binding.

## Provisioning workflow

### 1. Discover

1. Install the GOLD.i EA on the intended chart with orders disabled.
2. Confirm that no other order authority owns the same account, symbol, and
   magic.
3. Read account, terminal, symbol, leverage, and session properties from MT5.
4. Write a sanitized candidate binding and discovery report.
5. Emit `DISCOVERY_COMPLETE`; do not emit `PROFILE_VALIDATED` yet.

Discovery is read-only. Failure to read any required property leaves the EA
non-tradable.

### 2. Approve the binding

1. Compare the instrument economics with the certified GOLD.i contract.
2. Confirm the exact login, server, trade mode, terminal, and leverage.
3. Confirm dedicated state/spool paths and audience.
4. Generate canonical JSON and its fingerprint.
5. Store the approved binding outside source control; store only a sanitized
   template or checksum in Git.

Changing a candidate after approval invalidates its fingerprint.

### 3. Validate in DEMO

1. Restart MT5 and the EA using the approved DEMO binding.
2. Require `ENGINE_STARTED`, `BINDING_MATCHED`, `PROFILE_VALIDATED`, and
   `ENGINE_HEARTBEAT` events.
3. Keep order authority disabled for the first smoke run.
4. Exercise causal market-data ingestion, signal creation, restart recovery,
   notification routing, and duplicate suppression.
5. Enable DEMO order authority explicitly and complete the required forward
   validation window.

### 4. Promote to another account or REAL

Promotion never edits the DEMO binding.

1. Stop the DEMO instance and confirm its positions and watches are resolved or
   deliberately retained under the DEMO deployment.
2. Log in through a separate dedicated MT5 terminal.
3. Run discovery again on the destination account and symbol.
4. Create a new deployment ID, namespaces, and binding fingerprint.
5. Confirm the destination trade mode and observed leverage.
6. Run startup and broker preflight with orders disabled.
7. Require a human to activate the exact new binding fingerprint.
8. Start with no state copied from DEMO and monitor entry/close events.

No Telegram command alone may create a binding or promote DEMO to REAL.

## Runtime validation

The EA validates the following at `OnInit()` and immediately before every
order:

- profile family, strategy hash, binary hash, and binding fingerprint;
- exact symbol, login, server, account mode, leverage, terminal, and magic;
- current instrument fingerprint and trade-session availability;
- tick freshness, spread, price drift, and signal validity;
- lot tier, broker minimum/maximum/step, total exposure, and position count;
- free margin, `OrderCalcMargin`, `OrderCheck`, stops, freeze, and filling mode;
- duplicate signal, foreign position, and conflicting authority state.

Any mismatch emits one bounded health event, disables new orders, and requires
operator intervention. It must not retry notifications or write logs without a
bound.

## Account or symbol change while running

When MT5 reports a different login, server, mode, leverage, or symbol:

1. stop creating and submitting new orders immediately;
2. do not adopt the new identity;
3. preserve and report any positions owned by the previous binding;
4. emit `BINDING_INVALIDATED` once with sanitized old/new identifiers;
5. require a full discovery and approval cycle before resuming.

The EA must not close foreign or previously unowned positions as a side effect
of a binding mismatch.

## Required implementation and acceptance tests

Implementation is acceptable only when these tests pass:

- GOLD.i exact current account/symbol binding;
- another compatible 100-ounce gold symbol with a `0.01` volume step;
- symbol suffix change without approval is rejected;
- `GOLDm#` and a one-ounce contract are rejected;
- wrong login, server, DEMO/REAL mode, leverage, terminal, and magic are each
  rejected independently;
- minimum volume above the selected tier is rejected rather than rounded up;
- changed tick value, contract size, currency, or volume step invalidates the
  fingerprint;
- insufficient margin and broker `OrderCheck` rejection block submission;
- account switch during a watch and during an open position is fail-closed;
- restart restores only the exact deployment namespace;
- two EA instances cannot own the same deployment lease;
- no GOLDI event reaches the GOLDM namespace or audience;
- discovery and validation emit bounded storage and notification volume;
- compiled MQL5, Strategy Tester, DEMO E2E, restart, and rollback evidence are
  recorded for the portable release.

## Rollback

1. Disable the portable instance's order authority.
2. Stop only its dedicated terminal/task.
3. Preserve its binding, state, spool, positions, logs, and checksums.
4. Restore the previous certified GOLD.i binary and its exact DEMO binding.
5. Validate account, symbol, mode, leverage, magic, and binary hash.
6. Start with order authority disabled and require healthy startup receipts.

Rollback must not touch GOLDM and must never grant REAL authority.

## Implementation boundary

The current G21 release remains profile-locked and does not yet implement this
provisioner or dynamic binding document. Implementing this SOP requires a new
versioned GOLD.i release, regression/parity tests, actual MetaEditor compile,
DEMO E2E, restart evidence, and an explicit deployment decision. GOLDM source,
binary, configuration, and evidence must remain byte-for-byte unchanged during
that work.
