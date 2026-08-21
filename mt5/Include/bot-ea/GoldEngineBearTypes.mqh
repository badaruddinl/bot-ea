#ifndef GOLD_ENGINE_BEAR_TYPES_MQH
#define GOLD_ENGINE_BEAR_TYPES_MQH

#include "GoldEngineTypes.mqh"

enum BearIncrementalPhase
  {
   BEAR_PHASE_IDLE=0,
   BEAR_PHASE_WATCH_H1=1,
   BEAR_PHASE_WATCH_M5=2,
   BEAR_PHASE_WATCH_M1=3,
   BEAR_PHASE_ENTRY_READY=4,
   BEAR_PHASE_CANCELLED=5
  };

enum BearM5State
  {
   BEAR_M5_EXPIRED=0,
   BEAR_M5_ARMED=1,
   BEAR_M5_CANCELLED=2
  };

struct BearV4Config
  {
   int    h1_sma_period;
   int    m5_watch_bars;
   int    m5_touch_separation_bars;
   double m5_retreat_atr;
   int    m5_min_touches;
   int    m5_min_rejections;
   int    m5_acceptance_closes;
   int    m1_entry_bars;
   int    m1_min_touches;
   double m1_body_fraction;
   double m1_close_location;
   double stop_buffer_atr_m5;
   double price_tick;
   double spread_floor;
   double fixed_target_r;
   bool   has_fixed_target_r;
   double stop_multiplier;
   double target_multiplier;
  };

struct BearSetup
  {
   datetime time;
   string   symbol;
   string   reason;
   int      score;
   double   resistance;
   double   entry;
   double   stop;
   double   take_profit;
   double   reward_risk;
  };

struct BearM5Result
  {
   BearM5State state;
   string      reason;
   datetime    armed_at;
   double      atr;
   int         touches;
   int         rejections;
   double      recent_high;
  };

struct BearEntryPlan
  {
   bool     valid;
   datetime armed_at;
   datetime opened_at;
   double   entry;
   double   stop;
   double   target;
   double   structural_stop;
   double   structural_target;
   int      m5_touches;
   int      m5_rejections;
   int      m1_touches;
  };

void LoadBearV4Config(BearV4Config &config,const double spread_floor)
  {
   config.h1_sma_period=20;
   config.m5_watch_bars=12;
   config.m5_touch_separation_bars=2;
   config.m5_retreat_atr=0.25;
   config.m5_min_touches=1;
   config.m5_min_rejections=1;
   config.m5_acceptance_closes=2;
   config.m1_entry_bars=20;
   config.m1_min_touches=2;
   config.m1_body_fraction=0.35;
   config.m1_close_location=0.35;
   config.stop_buffer_atr_m5=0.10;
   config.price_tick=0.01;
   config.spread_floor=spread_floor;
   config.fixed_target_r=2.0;
   config.has_fixed_target_r=true;
   config.stop_multiplier=1.0;
   config.target_multiplier=1.0;
  }

#endif
