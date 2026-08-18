# GOLDM_REVISED 0.5.0 — 2020–2026 backtest attempt

## Requested scope

- Symbol: broker `GOLD.i#`
- Requested server-time range: 2020-01-01 through 2026-08-18
- Engine: stable `GOLDM_REVISED` 0.5.0
- Production terminal: read-only; no restart and no order API

## History coverage blocker

The production MT5 terminal reports `maxbars=100000`. Its earliest available
M1 candle is 2026-05-07 15:37 server time. The replay coverage check therefore
stopped the requested six-year run instead of silently reporting a partial
result as 2020–2026.

The loader was changed to request long history in bounded chunks and the
replay loop now uses rolling windows, but neither change can manufacture M1
bars that the terminal has not loaded.

## Available-history backtest

The complete available range from 2026-05-08 through 2026-08-18 produced:

- signals/resolved: 1000 / 1000;
- BUY: 536;
- SELL: 464;
- core BUY: 435;
- SCALPER: 101;
- targets: 391;
- stops: 569;
- other resolved outcomes: 40;
- total: `-47.166024R`;
- expectancy: `-0.047166R` per entry;
- maximum drawdown: `54.821102R`.

## Verdict

FAIL. The focused five-evidence improvement does not generalize to the full
available M1 history. Shadow/forward deployment remains disabled.

A genuine 2020–2026 M1 replay requires an isolated research terminal/clone
configured with a sufficiently large history limit and allowed to download
the broker archive. Restarting or reconfiguring the production terminal is not
an acceptable workaround.
