# G17 Full Happy-Path E2E

Status: **PASS**

Scope: SHARED, GOLDI, GOLDM, CROSS_PROFILE. Production REAL order authority
remained **DISABLED**.

## Complete chains

- GOLDI actual DEMO: account `108098316`, `XMGlobal-MT5 5`, `GOLD.i#`.
  Controlled final chain opened BUY `0.1`, modified SL, closed SELL, received
  retcodes `10009`, ended with zero positions, and emitted six correlated
  events. Native log SHA-256:
  `8ce133a39633b8b3f8ffed93bddc7c12b83a8d774993c798e85512fe3367e409`.
- GOLDM engineering: exact GOLDM profile on `GOLDm#` / `XMGlobal-MT5 14` in
  isolated Strategy Tester. BUY `2`, modify, close, all retcodes `10009`, zero
  positions, six correlated events. Native log SHA-256:
  `a5cca41620ab7286a4bf8dd47b0a70664f2ce1fcb43c85bc804d4f0cb7352614`.
- Correlation covers profile, setup, signal, order, position, event, DB row,
  and Telegram receipt. Canonical certification SHA-256:
  `8cac2ebc05f2d73d46a6fdc6ec697a1eb81bde962eb23c7d4b3c0d19acbc1494`.

## Routing and Telegram

- Actual native spools produced 12 unique SQLite rows with both offsets fully
  ACKed.
- Telegram policy delivered only READY/OPEN/CLOSE: nine recipient deliveries
  in the distinct capture matrix; SETUP/ORDER/MODIFY stayed DB-only.
- Actual dev Telegram Bot API delivered six messages with zero failures. The
  available dev chat served as both admin and approved recipient; this overlap
  is recorded explicitly. Distinct-role capture evidence proves GOLDM never
  routes to an approved-only GOLDI recipient.
- Receipt evidence contains Telegram message IDs and SHA-256 chat identifiers,
  never raw chat IDs or bot tokens. The development token is not stored in Git
  or external evidence.

## GOLDM refusal and safety

- Exact `BUILD_PROFILE_GOLDM` harness refused wrong account, wrong server, and
  DEMO trade mode; magic is `26081912`, authority default is disabled, final
  tester balance stayed 100.00 USD, and no order/deal mutation occurred.
- The production GOLDM entrypoint keeps `InpEnableOrderAuthority=false`; only a
  matching REAL binding plus explicit human input could request authority.
- GOLDI isolated clone was returned to Algo Trading OFF and closed cleanly.
  Main terminal settings were never changed.
- The initial live attempt failed closed with retcode `10027`. An older attached
  harness caused one additional `0.02` DEMO-only round trip after enablement;
  it was removed and all positions were verified closed before the controlled
  current `0.1` chain. No REAL account was touched.

## Compile and regression

- MetaEditor 6090: two production profile EAs and three G17 harnesses compiled
  with 0 errors and 0 warnings.
- Final production binary SHA-256: GOLDI
  `cf8ea0de6296c69a9f28291d955cebb4179eca12ddccb771a64a5e777ab7c9ba`,
  GOLDM `238238cc8ad7f77cfed27b8f2ba839ef0c3b0db6a5a64257c2feece8beec232c`.
- Full regression: 834 fast and 218 slow tests passed.
- Quality gate: Ruff/mypy clean, safety core 90.12%, changed strategy rules
  82.66%.
- External evidence/binaries:
  `E:\luthfi\project\bot-ea-evidence\BOT-EA-LIVE-ENGINE-MQL5-DUAL-PROFILE-E2E\b042d51cfc3b2ea1f9aa048054af03d79d79726e\G17-happy-path-e2e\final`.
- External `SHA256SUMS` SHA-256:
  `bb93840ebaf51368e6bd860e6d85bb026f259c76dc379bd300f1c50fc733b428`.

REAL orders: **DISABLED**
