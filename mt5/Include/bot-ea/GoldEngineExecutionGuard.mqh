#ifndef GOLD_ENGINE_EXECUTION_GUARD_MQH
#define GOLD_ENGINE_EXECUTION_GUARD_MQH

#include "GoldEngineTypes.mqh"

enum ExecutionRejectFlag
  {
   EXECUTION_REJECT_NONE              = 0,
   EXECUTION_REJECT_PROFILE           = 1 << 0,
   EXECUTION_REJECT_POLICY            = 1 << 1,
   EXECUTION_REJECT_AGE               = 1 << 2,
   EXECUTION_REJECT_DRIFT             = 1 << 3,
   EXECUTION_REJECT_SPREAD            = 1 << 4,
   EXECUTION_REJECT_INVALIDATION      = 1 << 5,
   EXECUTION_REJECT_ACCOUNT           = 1 << 6,
   EXECUTION_REJECT_SERVER_MODE       = 1 << 7,
   EXECUTION_REJECT_TERMINAL          = 1 << 8,
   EXECUTION_REJECT_SYMBOL            = 1 << 9,
   EXECUTION_REJECT_MAGIC             = 1 << 10,
   EXECUTION_REJECT_POSITION_COUNT    = 1 << 11,
   EXECUTION_REJECT_TOTAL_VOLUME      = 1 << 12,
   EXECUTION_REJECT_FREE_MARGIN       = 1 << 13,
   EXECUTION_REJECT_BROKER_CONSTRAINT = 1 << 14,
   EXECUTION_REJECT_DUPLICATE         = 1 << 15,
   EXECUTION_REJECT_GEOMETRY          = 1 << 16,
   EXECUTION_REJECT_BROKER_CHECK      = 1 << 17
  };

struct ExecutionContext
  {
   EngineTick              quote;
   long                    account_login;
   string                  account_server;
   ENUM_ACCOUNT_TRADE_MODE trade_mode;
   string                  terminal_identity;
   double                  free_margin;
   string                  symbol;
   double                  tick_size;
   double                  point;
   double                  volume_minimum;
   double                  volume_maximum;
   double                  volume_step;
   int                     stops_level_points;
   int                     freeze_level_points;
   bool                    trade_enabled;
   int                     position_count;
   double                  total_volume;
   bool                    duplicate_signal;
   double                  required_margin;
   bool                    broker_check_allowed;
   uint                    broker_check_retcode;
  };

struct ExecutionOrder
  {
   string     signal_id;
   string     symbol;
   EngineSide side;
   double     volume;
   double     price;
   double     stop_loss;
   double     take_profit;
   long       magic;
   int        deviation_points;
  };

struct ExecutionValidation
  {
   bool           allowed;
   ulong          reject_mask;
   string         primary_reason;
   double         drift_r;
   double         executable_price;
   ExecutionOrder order;
  };

void ExecutionReject(ulong &mask,const ExecutionRejectFlag flag)
  {
   mask|=(ulong)flag;
  }

bool ExecutionHasReject(const ulong mask,const ExecutionRejectFlag flag)
  {
   return (mask&(ulong)flag)!=0;
  }

string ExecutionRejectName(const ExecutionRejectFlag flag)
  {
   if(flag==EXECUTION_REJECT_PROFILE) return "PROFILE_MISMATCH";
   if(flag==EXECUTION_REJECT_POLICY) return "POLICY_MISMATCH";
   if(flag==EXECUTION_REJECT_AGE) return "SIGNAL_AGE_INVALID";
   if(flag==EXECUTION_REJECT_DRIFT) return "ENTRY_DRIFT_EXCEEDED";
   if(flag==EXECUTION_REJECT_SPREAD) return "SPREAD_EXCEEDED";
   if(flag==EXECUTION_REJECT_INVALIDATION) return "SETUP_INVALIDATED";
   if(flag==EXECUTION_REJECT_ACCOUNT) return "ACCOUNT_MISMATCH";
   if(flag==EXECUTION_REJECT_SERVER_MODE) return "SERVER_MODE_MISMATCH";
   if(flag==EXECUTION_REJECT_TERMINAL) return "TERMINAL_MISMATCH";
   if(flag==EXECUTION_REJECT_SYMBOL) return "SYMBOL_MISMATCH";
   if(flag==EXECUTION_REJECT_MAGIC) return "MAGIC_MISMATCH";
   if(flag==EXECUTION_REJECT_POSITION_COUNT) return "POSITION_COUNT_EXCEEDED";
   if(flag==EXECUTION_REJECT_TOTAL_VOLUME) return "TOTAL_VOLUME_EXCEEDED";
   if(flag==EXECUTION_REJECT_FREE_MARGIN) return "FREE_MARGIN_INSUFFICIENT";
   if(flag==EXECUTION_REJECT_BROKER_CONSTRAINT) return "BROKER_CONSTRAINT_REJECTED";
   if(flag==EXECUTION_REJECT_DUPLICATE) return "DUPLICATE_SIGNAL";
   if(flag==EXECUTION_REJECT_GEOMETRY) return "EXECUTABLE_GEOMETRY_INVALID";
   if(flag==EXECUTION_REJECT_BROKER_CHECK) return "BROKER_CHECK_REJECTED";
   return "OK";
  }

string ExecutionPrimaryReason(const ulong mask)
  {
   for(int bit=0;bit<=17;bit++)
     {
      const ulong value=((ulong)1)<<bit;
      if((mask&value)!=0)
         return ExecutionRejectName((ExecutionRejectFlag)value);
     }
   return "OK";
  }

bool ExecutionFinitePositive(const double value,const bool allow_zero=false)
  {
   if(!MathIsValidNumber(value))
      return false;
   return allow_zero ? value>=0.0 : value>0.0;
  }

bool ExecutionAligned(const double value,const double step)
  {
   if(!ExecutionFinitePositive(step) || !MathIsValidNumber(value))
      return false;
   const double units=value/step;
   return MathAbs(units-MathRound(units))<=1.0e-7;
  }

void ExecutionZeroOrder(ExecutionOrder &order)
  {
   order.signal_id="";
   order.symbol="";
   order.side=ENGINE_SIDE_NONE;
   order.volume=0.0;
   order.price=0.0;
   order.stop_loss=0.0;
   order.take_profit=0.0;
   order.magic=0;
   order.deviation_points=0;
  }

bool ValidateExecution(const SignalPlan &plan,
                       const ProfileConfig &profile,
                       const ExecutionContext &context,
                       ExecutionValidation &result)
  {
   result.allowed=false;
   result.reject_mask=0;
   result.primary_reason="";
   result.drift_r=0.0;
   result.executable_price=0.0;
   ExecutionZeroOrder(result.order);

   const bool quote_ok=context.quote.time_msc>0 &&
                       ExecutionFinitePositive(context.quote.bid) &&
                       ExecutionFinitePositive(context.quote.ask) &&
                       context.quote.ask>=context.quote.bid;
   const bool side_ok=plan.side==ENGINE_SIDE_BUY || plan.side==ENGINE_SIDE_SELL;
   const double executable=(plan.side==ENGINE_SIDE_BUY ?
                            context.quote.ask : context.quote.bid);
   result.executable_price=executable;
   if(!quote_ok || !side_ok || !ExecutionFinitePositive(plan.risk_price))
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_GEOMETRY);
   else
      // Signal geometry comes from MT5 bars (Bid).  BUY execution uses Ask,
      // but spread is validated independently below and must not be counted a
      // second time as price drift.
      {
       const double drift_reference=(plan.profile_id=="GOLDI" ?
                                     context.quote.bid : executable);
       result.drift_r=MathAbs(drift_reference-plan.planned_entry)/plan.risk_price;
      }

   if(plan.profile_id!=profile.profile_id ||
      plan.profile_version!=profile.profile_version ||
      plan.profile_fingerprint!=profile.profile_fingerprint)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_PROFILE);

   if(plan.maximum_drift_r!=profile.maximum_drift_r ||
      plan.maximum_spread!=profile.maximum_spread)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_POLICY);

   const datetime quote_time=(datetime)(context.quote.time_msc/1000);
   if(quote_time<plan.entry_ready_at || quote_time>plan.valid_until ||
      plan.valid_until-plan.entry_ready_at>profile.maximum_signal_age_seconds ||
      plan.valid_until<plan.entry_ready_at)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_AGE);

   if(!MathIsValidNumber(result.drift_r) ||
      result.drift_r>profile.maximum_drift_r)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_DRIFT);

   const double spread=context.quote.ask-context.quote.bid;
   if(!MathIsValidNumber(spread) || spread<0.0 || spread>profile.maximum_spread)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_SPREAD);

   if((plan.side==ENGINE_SIDE_BUY && executable<=plan.invalidation) ||
      (plan.side==ENGINE_SIDE_SELL && executable>=plan.invalidation))
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_INVALIDATION);

   if(context.account_login!=plan.account_login)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_ACCOUNT);
   const bool goldm_tester_mode=plan.engineering_tester &&
      profile.profile_id=="GOLDM" && MQLInfoInteger(MQL_TESTER);
   if(context.account_server!=plan.account_server ||
      context.trade_mode!=plan.trade_mode ||
      (plan.trade_mode!=profile.expected_trade_mode && !goldm_tester_mode))
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_SERVER_MODE);
   if(context.terminal_identity!=plan.terminal_identity ||
      plan.terminal_identity!=profile.terminal_identity)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_TERMINAL);
   if(context.symbol!=plan.symbol || plan.symbol!=profile.symbol)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_SYMBOL);
   if(plan.magic!=profile.magic)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_MAGIC);
   if(context.position_count>=profile.max_positions)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_POSITION_COUNT);
   if(context.total_volume+plan.volume>profile.max_total_lot)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_TOTAL_VOLUME);
   if(context.free_margin<context.required_margin)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_FREE_MARGIN);
   if(context.duplicate_signal)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_DUPLICATE);

   const double minimum_distance=
      MathMax(context.stops_level_points,context.freeze_level_points)*context.point;
   const bool constraints_ok=plan.executable && context.trade_enabled &&
      context.tick_size==profile.tick_size && plan.tick_size==profile.tick_size &&
      ExecutionFinitePositive(context.volume_minimum) &&
      ExecutionFinitePositive(context.volume_maximum) &&
      ExecutionFinitePositive(context.volume_step) &&
      context.volume_minimum<=plan.volume && plan.volume<=context.volume_maximum &&
      ExecutionAligned(plan.volume,context.volume_step) &&
      ExecutionAligned(plan.planned_entry,context.tick_size) &&
      ExecutionAligned(plan.stop_loss,context.tick_size) &&
      ExecutionAligned(plan.take_profit,context.tick_size) &&
      MathAbs(executable-plan.stop_loss)>=minimum_distance &&
      MathAbs(plan.take_profit-executable)>=minimum_distance;
   if(!constraints_ok)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_BROKER_CONSTRAINT);

   const bool geometry_ok=(plan.side==ENGINE_SIDE_BUY ?
      plan.stop_loss<executable && executable<plan.take_profit :
      plan.take_profit<executable && executable<plan.stop_loss);
   if(!geometry_ok)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_GEOMETRY);
   if(!context.broker_check_allowed)
      ExecutionReject(result.reject_mask,EXECUTION_REJECT_BROKER_CHECK);

   result.primary_reason=ExecutionPrimaryReason(result.reject_mask);
   result.allowed=result.reject_mask==0;
   if(!result.allowed)
      return false;

   result.order.signal_id=plan.signal_id;
   result.order.symbol=plan.symbol;
   result.order.side=plan.side;
   result.order.volume=plan.volume;
   result.order.price=executable;
   result.order.stop_loss=plan.stop_loss;
   result.order.take_profit=plan.take_profit;
   result.order.magic=plan.magic;
   result.order.deviation_points=profile.deviation_points;
   return true;
  }

#endif
