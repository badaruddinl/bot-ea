#ifndef GOLD_ENGINE_REVISED_TYPES_MQH
#define GOLD_ENGINE_REVISED_TYPES_MQH

#include "GoldEngineTypes.mqh"

enum RevisedState
  {
   REVISED_STATE_WAIT = 0,
   REVISED_STATE_WATCH = 1,
   REVISED_STATE_ENTRY_READY = 2,
   REVISED_STATE_CANCELLED = 3
  };

enum RevisedAction
  {
   REVISED_ACTION_OBSERVE = 0,
   REVISED_ACTION_ENTER = 1,
   REVISED_ACTION_CANCEL = 2
  };

enum RevisedConfirmationMode
  {
   REVISED_MODE_NONE = 0,
   REVISED_MODE_RANGE = 1,
   REVISED_MODE_MOMENTUM = 2
  };

struct RevisedEngineConfig
  {
   string symbol;
   double price_tick;
   double spread_floor;
   int    atr_period;
   int    range_min_bars;
   int    range_max_bars;
   int    range_touch_separation_bars;
   double range_retreat_fraction;
   int    range_min_rejections;
   double range_min_excursion_fraction;
   double range_min_body_fraction;
   double range_min_close_location;
   int    acceptance_close_count;
   int    acceptance_window;
   double acceptance_displacement_atr;
   int    momentum_bars;
   double momentum_min_displacement_atr;
   double momentum_min_body_fraction;
   double momentum_close_location;
   double momentum_max_opposite_wick_fraction;
   int    exhaustion_min_signals;
   double first_obstacle_reject_r;
   double first_obstacle_strict_r;
   double scalper_min_obstacle_r;
   double strict_target_buffer_atr;
   double scalper_target_buffer_atr;
   double stop_buffer_atr;
   double adaptive_stop_buffer_atr;
   double adaptive_stop_min_risk_atr;
   double strong_m1_body_ratio;
   double strong_m1_close_location;
   double supply_displacement_atr;
   int    supply_confirmation_bars;
   int    zone_acceptance_closes;
   double h1_supply_breakout_trend_min_atr;
   double h1_supply_breakout_trend_max_atr;
   double h1_supply_breakout_max_efficiency;
   int    watch_max_m1_bars;
   int    fibonacci_lookback_m5;
   int    fibonacci_retest_separation_bars;
   double fibonacci_leave_fraction;
   int    swing_span;
   int    minimum_m5_votes;
   double promotion_confidence;
  };

class CRevisedSnapshot
  {
public:
   string     symbol;
   EngineSide side;
   datetime   current_time;
   EngineBar  m1_bars[];
   EngineBar  m5_bars[];
   EngineBar  h1_bars[];
   EngineBar  d1_bars[];
   datetime   m5_trigger_time;
   string     m5_pattern;
   int        m5_votes;
   double     confidence;
   double     level;
   bool       has_level;
   double     invalidation;
   bool       has_invalidation;
   double     entry;
   bool       has_entry;
   double     stop;
   bool       has_stop;

   CRevisedSnapshot(void)
     {
      symbol="";
      side=ENGINE_SIDE_NONE;
      current_time=0;
      m5_trigger_time=0;
      m5_pattern="NONE";
      m5_votes=0;
      confidence=0.0;
      level=0.0;
      has_level=false;
      invalidation=0.0;
      has_invalidation=false;
      entry=0.0;
      has_entry=false;
      stop=0.0;
      has_stop=false;
     }
  };

struct RevisedDecision
  {
   string                  strategy_id;
   string                  strategy_version;
   string                  symbol;
   EngineSide              side;
   RevisedState            state;
   RevisedAction           action;
   string                  entry_profile;
   bool                    observation_only;
   datetime                setup_trigger_time;
   datetime                time;
   string                  reason;
   string                  validation_status;
   int                     retest_count;
   double                  confidence;
   RevisedConfirmationMode mode;
   bool                    exhausted;
   bool                    has_entry;
   double                  entry;
   bool                    has_stop;
   double                  stop;
   bool                    has_target;
   double                  target;
   bool                    has_first_obstacle;
   double                  first_obstacle;
   string                  first_obstacle_kind;
   bool                    has_first_obstacle_r;
   double                  first_obstacle_r;
   int                     touch_count;
   int                     rejection_count;
   int                     acceptance_count;
   int                     m1_votes;
  };

struct RevisedRangeStats
  {
   int    bars;
   double high;
   double low;
   double width;
   int    touches;
   int    rejections;
   int    acceptance;
   double excursion;
   double boundary;
  };

struct RevisedM1Confirmation
  {
   int    votes;
   bool   directional;
   bool   micro_break;
   bool   rsi_ok;
   double rsi7;
   double body_ratio;
   double close_location;
  };

struct RevisedMomentumStats
  {
   bool   momentum;
   bool   exhausted;
   double displacement_atr;
   double body_ratio;
   double close_location;
   int    exhaustion_signals;
  };

struct RevisedFibonacciStats
  {
   bool   available;
   double anchor_start;
   double anchor_end;
   double zone_low;
   double zone_high;
   int    retests;
   bool   current_rejection;
  };

struct RevisedRiskStats
  {
   string source;
   double original_stop;
   double selected_stop;
   double risk;
   int    m1_pivot_count;
  };

void LoadRevisedConfig(RevisedEngineConfig &config,const string symbol)
  {
   config.symbol=symbol;
   config.price_tick=0.01;
   config.spread_floor=0.20;
   config.atr_period=14;
   config.range_min_bars=4;
   config.range_max_bars=12;
   config.range_touch_separation_bars=2;
   config.range_retreat_fraction=0.25;
   config.range_min_rejections=2;
   config.range_min_excursion_fraction=0.50;
   config.range_min_body_fraction=0.35;
   config.range_min_close_location=0.65;
   config.acceptance_close_count=2;
   config.acceptance_window=4;
   config.acceptance_displacement_atr=0.50;
   config.momentum_bars=3;
   config.momentum_min_displacement_atr=0.80;
   config.momentum_min_body_fraction=0.55;
   config.momentum_close_location=0.75;
   config.momentum_max_opposite_wick_fraction=1.0;
   config.exhaustion_min_signals=2;
   config.first_obstacle_reject_r=1.0;
   config.first_obstacle_strict_r=1.5;
   config.scalper_min_obstacle_r=0.10;
   config.strict_target_buffer_atr=0.12;
   config.scalper_target_buffer_atr=0.03;
   config.stop_buffer_atr=0.18;
   config.adaptive_stop_buffer_atr=0.10;
   config.adaptive_stop_min_risk_atr=0.35;
   config.strong_m1_body_ratio=0.55;
   config.strong_m1_close_location=0.75;
   config.supply_displacement_atr=0.80;
   config.supply_confirmation_bars=3;
   config.zone_acceptance_closes=2;
   config.h1_supply_breakout_trend_min_atr=0.0;
   config.h1_supply_breakout_trend_max_atr=2.0;
   config.h1_supply_breakout_max_efficiency=0.20;
   config.watch_max_m1_bars=60;
   config.fibonacci_lookback_m5=12;
   config.fibonacci_retest_separation_bars=2;
   config.fibonacci_leave_fraction=0.25;
   config.swing_span=2;
   config.minimum_m5_votes=2;
   config.promotion_confidence=60.0;
  }

#endif
