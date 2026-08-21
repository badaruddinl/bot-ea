#ifndef GOLD_ENGINE_TYPES_MQH
#define GOLD_ENGINE_TYPES_MQH

enum EngineSide
  {
   ENGINE_SIDE_NONE = 0,
   ENGINE_SIDE_BUY = 1,
   ENGINE_SIDE_SELL = -1
  };

enum EngineStrategyPhase
  {
   ENGINE_PHASE_IDLE = 0,
   ENGINE_PHASE_WATCH = 1,
   ENGINE_PHASE_ENTRY_READY = 2,
   ENGINE_PHASE_POSITION_OPEN = 3,
   ENGINE_PHASE_CANCELLED = 4
  };

enum EngineDecisionAction
  {
   ENGINE_ACTION_NONE = 0,
   ENGINE_ACTION_WATCH = 1,
   ENGINE_ACTION_OPEN = 2,
   ENGINE_ACTION_MODIFY = 3,
   ENGINE_ACTION_CLOSE = 4,
   ENGINE_ACTION_REJECT = 5
  };

enum EngineEventType
  {
   ENGINE_EVENT_NONE = 0,
   ENGINE_EVENT_RUNTIME_READY = 1,
   ENGINE_EVENT_BAR_CLOSED = 2,
   ENGINE_EVENT_DATA_GAP = 3,
   ENGINE_EVENT_ENTRY_READY = 4,
   ENGINE_EVENT_POSITION = 5,
   ENGINE_EVENT_ERROR = 6
  };

struct EngineBar
  {
   ENUM_TIMEFRAMES timeframe;
   datetime        open_time;
   datetime        close_time;
   double          open;
   double          high;
   double          low;
   double          close;
   long            tick_volume;
   int             spread_points;
  };

struct EngineTick
  {
   long   time_msc;
   double bid;
   double ask;
   double last;
  };

struct ProfileConfig
  {
   string                  profile_id;
   string                  profile_version;
   string                  profile_fingerprint;
   string                  strategy_version;
   string                  symbol;
   string                  terminal_identity;
   long                    magic;
   ENUM_ACCOUNT_TRADE_MODE expected_trade_mode;
   bool                    order_authority_default;
   int                     sizing_tier_count;
   double                  sizing_minimum_balance[9];
   double                  sizing_lot[9];
   int                     max_positions;
   double                  max_total_lot;
   int                     deviation_points;
   double                  tick_size;
   double                  maximum_drift_r;
   double                  maximum_spread;
   int                     maximum_signal_age_seconds;
  };

struct StrategyState
  {
   EngineStrategyPhase phase;
   bool                warmed;
   bool                active_setup;
   datetime            setup_created_at;
   long                bars_processed;
   string              setup_id;
  };

struct StrategyDecision
  {
   EngineDecisionAction action;
   EngineSide           side;
   datetime             decided_at;
   double               confidence;
   string               reason;
  };

struct SignalPlan
  {
   string     profile_id;
   string     profile_version;
   string     profile_fingerprint;
   string     strategy_version;
   string     setup_id;
   string     signal_id;
   string     symbol;
   EngineSide side;
   long       account_login;
   string     account_server;
   ENUM_ACCOUNT_TRADE_MODE trade_mode;
   string     terminal_identity;
   long       magic;
   datetime   setup_created_at;
   datetime   entry_ready_at;
   datetime   valid_until;
   double     volume;
   double     tick_size;
   double     maximum_drift_r;
   double     maximum_spread;
   double     planned_entry;
   double     stop_loss;
   double     take_profit;
   double     invalidation;
   double     risk_price;
   bool       executable;
  };

struct EngineEvent
  {
   EngineEventType type;
   string          profile_id;
   string          event_id;
   datetime        server_time;
   string          reason;
  };

struct ManagedPosition
  {
   ulong      ticket;
   string     profile_id;
   long       magic;
   EngineSide side;
   datetime   opened_at;
   double     volume;
   double     entry_price;
   double     stop_loss;
   double     take_profit;
   string     comment;
   bool       owned;
  };

#endif
