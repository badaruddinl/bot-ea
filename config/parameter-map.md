# Parameter Map

## User parameters

- `trading_style`
  - `scalping`
  - `intraday`
  - `swing`
- `market_allowlist`
  - examples: `EURUSD`, `XAUUSD`, `US30`
- `risk_profile`
  - `conservative`
  - `normal`
  - `aggressive`
- `account_mode`
  - `demo`
  - `live`
- `daily_loss_limit_pct`
- `max_positions`
- `session_preference`

## Auto-derived from MT5

- `equity`
- `balance`
- `free_margin`
- `margin_level`
- `symbol.spread`
- `symbol.volume_min`
- `symbol.volume_max`
- `symbol.volume_step`
- `symbol.trade_stops_level`
- `symbol.trade_contract_size`
- `symbol.tick_size`
- `symbol.tick_value`
- `symbol.session_state`
- `current_open_risk`

## Tuned parameters

- `sl_model`
- `sl_multiplier`
- `tp_model`
- `tp_multiplier`
- `min_rr`
- `spread_cap_points`
- `spread_cap_ratio`
- `min_volatility_threshold`
- `max_volatility_threshold`
- `entry_quality_threshold`
- `cooldown_after_loss_minutes`
- `session_enabled_flags`
- `news_blackout_before_minutes`
- `news_blackout_after_minutes`

## Risk policy defaults to test first

These are design starting points, not validated live settings.

### Small equity

- `risk_per_trade_pct = 0.25 to 0.50`
- `max_total_open_risk_pct = 1.0 to 1.5`
- `daily_loss_limit_pct = 1.5 to 2.0`

### Medium equity

- `risk_per_trade_pct = 0.50 to 0.75`
- `max_total_open_risk_pct = 2.0 to 3.0`
- `daily_loss_limit_pct = 2.0 to 3.0`

### Strict mode overrides

- halve baseline `risk_per_trade_pct`
- force `max_positions = 1`
- require stronger setup quality
- disable trading around high-impact news
- tighten spread filter
