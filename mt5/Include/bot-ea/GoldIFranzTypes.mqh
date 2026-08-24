#ifndef GOLDI_FRANZ_TYPES_MQH
#define GOLDI_FRANZ_TYPES_MQH

enum FranzMode
  {
   FRANZ_MODE_NONE=0,
   FRANZ_MODE_HANDGUN_RANGE=1,
   FRANZ_MODE_SNIPER_TREND=2
  };

enum FranzSide
  {
   FRANZ_SIDE_NONE=0,
   FRANZ_SIDE_BUY=1,
   FRANZ_SIDE_SELL=-1
  };

enum FranzState
  {
   FRANZ_STATE_COLD=0,
   FRANZ_STATE_IDLE=1,
   FRANZ_STATE_REGIME_SELECTED=2,
   FRANZ_STATE_EXTREME_WATCH=3,
   FRANZ_STATE_BREAK_ATTEMPT=4,
   FRANZ_STATE_BREAK_FAILED=5,
   FRANZ_STATE_SHAKEOUT_CONFIRMED=6,
   FRANZ_STATE_FIB_RECLAIMED=7,
   FRANZ_STATE_ENTRY_READY=8,
   FRANZ_STATE_POSITION_OPEN=9,
   FRANZ_STATE_EXIT_PENDING=10,
   FRANZ_STATE_CLOSED=11,
   FRANZ_STATE_EXPIRED=12,
   FRANZ_STATE_CANCELLED=13,
   FRANZ_STATE_FAILED=14,
   FRANZ_STATE_DAILY_LOCKED=15
  };

struct FranzBar
  {
   datetime open_time;
   datetime close_time;
   double   open;
   double   high;
   double   low;
   double   close;
   long     tick_volume;
   double   spread;
  };

struct FranzFibonacci
  {
   bool   locked;
   double anchor_a;
   double anchor_b;
   double range;
   double level_236;
   double level_382;
   double level_500;
   double level_618;
   double level_1000;
   double level_1130;
   double level_1272;
  };

struct FranzTrendlineZone
  {
   bool     valid;
   datetime projected_at;
   double   center_at_projection;
   double   slope_per_second;
   double   half_width;
   int      touches;
  };

struct FranzSwingZone
  {
   bool     valid;
   bool     supply;
   datetime created_at;
   double   proximal;
   double   distal;
   double   median_range;
   double   departure_strength;
   int      bounces;
   datetime last_touch_at;
   bool     invalidated;
  };

struct FranzDecision
  {
   FranzState state;
   FranzMode  mode;
   FranzSide  side;
   string     setup_id;
   string     signal_id;
   datetime   setup_created_at;
   datetime   entry_ready_at;
   datetime   valid_until;
   double     liquidity_reference;
   double     sweep_extreme;
   double     cluster_high;
   double     cluster_low;
   int        touches;
   int        direction_changes;
   int        reentry_closes;
   bool       sweep_confirmed;
   bool       micro_break_confirmed;
   int        rsi_votes;
   bool       stochastic_reinforced;
   FranzTrendlineZone bull_zone;
   FranzTrendlineZone bear_zone;
   FranzSwingZone supply_zone;
   FranzSwingZone demand_zone;
   bool       initial_trendline_break;
   double     initial_break_level;
   FranzFibonacci fibonacci;
   double     entry;
   double     stop_loss;
   double     take_profit_1;
   double     take_profit_2;
   double     projected_r_1;
   double     projected_r_2;
   string     reason;
  };

struct FranzPersistentState
  {
   ulong      generation;
   FranzState state;
   FranzMode  mode;
   FranzSide  side;
   int        day_key;
   int        daily_setups;
   double     daily_r;
   datetime   cooldown_until;
   datetime   last_m15_close;
   datetime   last_m5_close;
   datetime   last_m1_close;
   string     setup_id;
   datetime   setup_created_at;
   datetime   setup_expires_at;
   int        watch_m1_bars;
   int        break_m1_bars;
   int        fib_m1_bars;
   double     liquidity_reference;
   double     sweep_extreme;
   double     cluster_high;
   double     cluster_low;
   double     rejection_high;
   double     rejection_low;
   int        reentry_closes;
   FranzTrendlineZone bull_zone;
   FranzTrendlineZone bear_zone;
   FranzSwingZone supply_zone;
   FranzSwingZone demand_zone;
   bool       initial_trendline_break;
   double     initial_break_level;
   FranzFibonacci fibonacci;
   double     planned_entry;
   double     stop_loss;
   double     take_profit_1;
   double     take_profit_2;
   double     initial_risk_price;
   double     setup_risk_usd;
   ulong      leg1_ticket;
   ulong      leg2_ticket;
   ulong      leg1_position_id;
   ulong      leg2_position_id;
   bool       leg1_closed;
   bool       leg2_closed;
   bool       tp1_hit;
   datetime   position_opened_at;
   double     setup_realized_pnl;
   int        cleanup_attempts;
   ulong      cleanup_started_ms;
   string     close_reason;
  };

void FranzResetFibonacci(FranzFibonacci &value)
  {
   ZeroMemory(value);
  }

void FranzResetTrendlineZone(FranzTrendlineZone &value)
  {
   ZeroMemory(value);
  }

void FranzResetSwingZone(FranzSwingZone &value)
  {
   ZeroMemory(value);
  }

void FranzResetDecision(FranzDecision &value)
  {
   ZeroMemory(value);
   value.state=FRANZ_STATE_IDLE;
   value.mode=FRANZ_MODE_NONE;
   value.side=FRANZ_SIDE_NONE;
   FranzResetTrendlineZone(value.bull_zone);
   FranzResetTrendlineZone(value.bear_zone);
   FranzResetSwingZone(value.supply_zone);
   FranzResetSwingZone(value.demand_zone);
   FranzResetFibonacci(value.fibonacci);
  }

void FranzResetPersistentState(FranzPersistentState &value)
  {
   ZeroMemory(value);
   value.state=FRANZ_STATE_COLD;
   value.mode=FRANZ_MODE_NONE;
   value.side=FRANZ_SIDE_NONE;
   FranzResetTrendlineZone(value.bull_zone);
   FranzResetTrendlineZone(value.bear_zone);
   FranzResetSwingZone(value.supply_zone);
   FranzResetSwingZone(value.demand_zone);
   FranzResetFibonacci(value.fibonacci);
  }

string FranzModeName(const FranzMode mode)
  {
   if(mode==FRANZ_MODE_HANDGUN_RANGE) return "HANDGUN_RANGE";
   if(mode==FRANZ_MODE_SNIPER_TREND) return "SNIPER_TREND";
   return "NONE";
  }

string FranzSideName(const FranzSide side)
  {
   if(side==FRANZ_SIDE_BUY) return "BUY";
   if(side==FRANZ_SIDE_SELL) return "SELL";
   return "NONE";
  }

#endif
