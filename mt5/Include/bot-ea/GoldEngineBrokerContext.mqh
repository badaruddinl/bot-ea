#ifndef GOLD_ENGINE_BROKER_CONTEXT_MQH
#define GOLD_ENGINE_BROKER_CONTEXT_MQH

#include "GoldEngineExecutionGuard.mqh"

struct BrokerPreflight
  {
   bool                request_built;
   bool                check_called;
   MqlTradeRequest     request;
   MqlTradeCheckResult check_result;
  };

string ExecutionSignalComment(const string profile_id,const string signal_id)
  {
   const int keep=16;
   const int start=MathMax(0,StringLen(signal_id)-keep);
   return "GE|"+profile_id+"|"+StringSubstr(signal_id,start);
  }

ENUM_ORDER_TYPE_FILLING ExecutionResolveFilling(const string symbol)
  {
   const long execution=SymbolInfoInteger(symbol,SYMBOL_TRADE_EXEMODE);
   const int modes=(int)SymbolInfoInteger(symbol,SYMBOL_FILLING_MODE);
   if(execution!=SYMBOL_TRADE_EXECUTION_MARKET)
      return ORDER_FILLING_RETURN;
   if((modes&SYMBOL_FILLING_FOK)==SYMBOL_FILLING_FOK)
      return ORDER_FILLING_FOK;
   if((modes&SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC)
      return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
  }

void ExecutionResetPreflight(BrokerPreflight &preflight)
  {
   preflight.request_built=false;
   preflight.check_called=false;
   ZeroMemory(preflight.request);
   ZeroMemory(preflight.check_result);
  }

bool ExecutionBuildRequest(const SignalPlan &plan,
                           const ProfileConfig &profile,
                           const EngineTick &quote,
                           MqlTradeRequest &request,
                           string &reason)
  {
   ZeroMemory(request);
   if(plan.side!=ENGINE_SIDE_BUY && plan.side!=ENGINE_SIDE_SELL)
     {
      reason="REQUEST_SIDE_INVALID";
      return false;
     }
   if(plan.profile_id!=profile.profile_id || plan.symbol!=profile.symbol ||
      plan.magic!=profile.magic)
     {
      reason="REQUEST_IDENTITY_MISMATCH";
      return false;
     }
   request.action=TRADE_ACTION_DEAL;
   request.magic=(ulong)plan.magic;
   request.symbol=plan.symbol;
   request.volume=plan.volume;
   request.type=(plan.side==ENGINE_SIDE_BUY ? ORDER_TYPE_BUY : ORDER_TYPE_SELL);
   request.price=(plan.side==ENGINE_SIDE_BUY ? quote.ask : quote.bid);
   request.sl=plan.stop_loss;
   request.tp=plan.take_profit;
   request.deviation=(ulong)profile.deviation_points;
   request.type_filling=ExecutionResolveFilling(plan.symbol);
   request.type_time=ORDER_TIME_GTC;
   request.comment=ExecutionSignalComment(plan.profile_id,plan.signal_id);
   reason="OK";
   return true;
  }

bool ExecutionCollectExposure(const SignalPlan &plan,
                              const ProfileConfig &profile,
                              int &position_count,
                              double &total_volume,
                              bool &duplicate_signal,
                              string &reason)
  {
   position_count=0;
   total_volume=0.0;
   duplicate_signal=false;
   const string comment=ExecutionSignalComment(plan.profile_id,plan.signal_id);
   const int total=PositionsTotal();
   if(total<0)
     {
      reason="POSITIONS_TOTAL_INVALID";
      return false;
     }
   for(int index=0;index<total;index++)
     {
      const ulong ticket=PositionGetTicket(index);
      if(ticket==0 || !PositionSelectByTicket(ticket))
        {
         reason="POSITION_DISCOVERY_FAILED";
         return false;
        }
      if(PositionGetString(POSITION_SYMBOL)!=profile.symbol ||
         PositionGetInteger(POSITION_MAGIC)!=profile.magic)
         continue;
      position_count++;
      total_volume+=PositionGetDouble(POSITION_VOLUME);
      if(PositionGetString(POSITION_COMMENT)==comment)
         duplicate_signal=true;
     }
   reason="OK";
   return true;
  }

bool ExecutionCollectBrokerContext(const SignalPlan &plan,
                                   const ProfileConfig &profile,
                                   ExecutionContext &context,
                                   BrokerPreflight &preflight,
                                   string &reason)
  {
   ZeroMemory(context);
   ExecutionResetPreflight(preflight);
   if(plan.symbol!=profile.symbol || _Symbol!=profile.symbol)
     {
      reason="BROKER_SYMBOL_MISMATCH";
      return false;
     }

   MqlTick tick;
   if(!SymbolInfoTick(profile.symbol,tick) || tick.time_msc<=0)
     {
      reason="BROKER_TICK_UNAVAILABLE";
      return false;
     }
   context.quote.time_msc=tick.time_msc;
   context.quote.bid=tick.bid;
   context.quote.ask=tick.ask;
   context.quote.last=tick.last;
   context.account_login=AccountInfoInteger(ACCOUNT_LOGIN);
   context.account_server=AccountInfoString(ACCOUNT_SERVER);
   context.trade_mode=(ENUM_ACCOUNT_TRADE_MODE)AccountInfoInteger(ACCOUNT_TRADE_MODE);
   context.terminal_identity=profile.terminal_identity;
   context.free_margin=AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   context.symbol=profile.symbol;
   context.tick_size=SymbolInfoDouble(profile.symbol,SYMBOL_TRADE_TICK_SIZE);
   context.point=SymbolInfoDouble(profile.symbol,SYMBOL_POINT);
   context.volume_minimum=SymbolInfoDouble(profile.symbol,SYMBOL_VOLUME_MIN);
   context.volume_maximum=SymbolInfoDouble(profile.symbol,SYMBOL_VOLUME_MAX);
   context.volume_step=SymbolInfoDouble(profile.symbol,SYMBOL_VOLUME_STEP);
   context.stops_level_points=(int)SymbolInfoInteger(profile.symbol,SYMBOL_TRADE_STOPS_LEVEL);
   context.freeze_level_points=(int)SymbolInfoInteger(profile.symbol,SYMBOL_TRADE_FREEZE_LEVEL);
   const ENUM_SYMBOL_TRADE_MODE symbol_mode=
      (ENUM_SYMBOL_TRADE_MODE)SymbolInfoInteger(profile.symbol,SYMBOL_TRADE_MODE);
   const long order_mode=SymbolInfoInteger(profile.symbol,SYMBOL_ORDER_MODE);
   context.trade_enabled=symbol_mode==SYMBOL_TRADE_MODE_FULL &&
      (order_mode&SYMBOL_ORDER_MARKET)==SYMBOL_ORDER_MARKET &&
      (order_mode&SYMBOL_ORDER_SL)==SYMBOL_ORDER_SL &&
      (order_mode&SYMBOL_ORDER_TP)==SYMBOL_ORDER_TP;

   if(!ExecutionCollectExposure(
         plan,profile,context.position_count,context.total_volume,
         context.duplicate_signal,reason))
      return false;

   const ENUM_ORDER_TYPE order_type=(plan.side==ENGINE_SIDE_BUY ?
      ORDER_TYPE_BUY : ORDER_TYPE_SELL);
   const double executable=(plan.side==ENGINE_SIDE_BUY ? tick.ask : tick.bid);
   if(!OrderCalcMargin(
         order_type,profile.symbol,plan.volume,executable,context.required_margin) ||
      !ExecutionFinitePositive(context.required_margin))
     {
      reason="BROKER_MARGIN_CALC_FAILED";
      return false;
     }

   if(!ExecutionBuildRequest(plan,profile,context.quote,preflight.request,reason))
      return false;
   preflight.request_built=true;
   preflight.check_called=true;
   const bool checked=OrderCheck(preflight.request,preflight.check_result);
   context.broker_check_allowed=checked;
   context.broker_check_retcode=preflight.check_result.retcode;
   reason=(checked ? "OK" : "BROKER_ORDER_CHECK_FAILED");
   return checked;
  }

#endif
