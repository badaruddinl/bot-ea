#ifndef GOLDI_FRANZ_RUNTIME_MQH
#define GOLDI_FRANZ_RUNTIME_MQH

#include <Trade/Trade.mqh>
#include "GoldIFranzPersistence.mqh"
#include "GoldIFranzAudit.mqh"

class CGoldIFranzRuntime
  {
private:
   CTrade                 m_trade;
   CFranzStateStore       m_store;
   CFranzAudit            m_audit;
   FranzPersistentState   m_state;
   bool                   m_initialized;
   bool                   m_authority;
   bool                   m_data_healthy;
   int                    m_rsi_m1;
   int                    m_rsi_m5;
   int                    m_stochastic_m1;
   bool                   m_use_rsi;
   bool                   m_use_stochastic;
   bool                   m_use_fibonacci_gate;

   int ServerDayKey(const datetime server_time) const
     {
      MqlDateTime value;
      TimeToStruct(server_time,value);
      return value.year*1000+value.day_of_year;
     }

   string CompactSetupId(const datetime server_time,const FranzSide side) const
     {
      return "FRZ"+IntegerToString(ServerDayKey(server_time))+"-"+
         IntegerToString((long)server_time)+"-"+(side==FRANZ_SIDE_BUY ? "B" : "S");
     }

   string LegComment(const int leg) const
     {
      return "FRZ|"+IntegerToString((long)m_state.setup_created_at)+"|T"+
         IntegerToString(leg);
     }

   bool OwnComment(const string comment) const
     {
      return StringFind(comment,"FRZ|")==0;
     }

   bool TradeRetcodeOk(void) const
     {
      const uint value=m_trade.ResultRetcode();
      return value==TRADE_RETCODE_DONE || value==TRADE_RETCODE_PLACED ||
             value==TRADE_RETCODE_DONE_PARTIAL || value==TRADE_RETCODE_NO_CHANGES;
     }

   bool ValidateContract(string &reason) const
     {
      if(!(bool)MQLInfoInteger(MQL_TESTER))
        { reason="TESTER_ONLY_EA"; return false; }
      if(_Symbol!=FRANZ_SYMBOL)
        { reason="WRONG_SYMBOL"; return false; }
      if((ENUM_ACCOUNT_MARGIN_MODE)AccountInfoInteger(ACCOUNT_MARGIN_MODE)!=
         ACCOUNT_MARGIN_MODE_RETAIL_HEDGING)
        { reason="HEDGING_ACCOUNT_REQUIRED"; return false; }
      if(AccountInfoInteger(ACCOUNT_LEVERAGE)!=1000)
        { reason="LEVERAGE_MISMATCH"; return false; }
      if(MathAbs(SymbolInfoDouble(FRANZ_SYMBOL,SYMBOL_TRADE_CONTRACT_SIZE)-100.0)>1e-8)
        { reason="CONTRACT_SIZE_MISMATCH"; return false; }
      if(MathAbs(SymbolInfoDouble(FRANZ_SYMBOL,SYMBOL_TRADE_TICK_SIZE)-0.01)>1e-8)
        { reason="TICK_SIZE_MISMATCH"; return false; }
      if(MathAbs(SymbolInfoDouble(FRANZ_SYMBOL,SYMBOL_VOLUME_MIN)-0.01)>1e-8 ||
         MathAbs(SymbolInfoDouble(FRANZ_SYMBOL,SYMBOL_VOLUME_STEP)-0.01)>1e-8 ||
         MathAbs(SymbolInfoDouble(FRANZ_SYMBOL,SYMBOL_VOLUME_MAX)-50.0)>1e-8)
        { reason="VOLUME_CONTRACT_MISMATCH"; return false; }
      reason="PROFILE_VALID";
      return true;
     }

   bool LoadBars(const ENUM_TIMEFRAMES timeframe,const int count,FranzBar &result[]) const
     {
      MqlRates source[];
      ArraySetAsSeries(source,true);
      if(CopyRates(FRANZ_SYMBOL,timeframe,1,count,source)!=count) return false;
      ArrayResize(result,count);
      for(int index=0;index<count;index++)
        {
         result[index].open_time=source[index].time;
         result[index].close_time=source[index].time+PeriodSeconds(timeframe);
         result[index].open=source[index].open;
         result[index].high=source[index].high;
         result[index].low=source[index].low;
         result[index].close=source[index].close;
         result[index].tick_volume=source[index].tick_volume;
         result[index].spread=source[index].spread*SymbolInfoDouble(FRANZ_SYMBOL,SYMBOL_POINT);
        }
      return true;
     }

   bool CopyIndicator(const int handle,const int buffer,const int count,double &values[]) const
     {
      ArrayResize(values,count);
      ArraySetAsSeries(values,true);
      return handle!=INVALID_HANDLE && CopyBuffer(handle,buffer,1,count,values)==count;
     }

   int OwnPositions(ulong &tickets[]) const
     {
      ArrayResize(tickets,0);
      for(int index=PositionsTotal()-1;index>=0;index--)
        {
         const ulong ticket=PositionGetTicket(index);
         if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
         if(PositionGetString(POSITION_SYMBOL)!=FRANZ_SYMBOL ||
            PositionGetInteger(POSITION_MAGIC)!=FRANZ_MAGIC ||
            !OwnComment(PositionGetString(POSITION_COMMENT))) continue;
         const int size=ArraySize(tickets);
         ArrayResize(tickets,size+1);
         tickets[size]=ticket;
        }
      return ArraySize(tickets);
     }

   int OwnOrders(ulong &tickets[]) const
     {
      ArrayResize(tickets,0);
      for(int index=OrdersTotal()-1;index>=0;index--)
        {
         const ulong ticket=OrderGetTicket(index);
         if(ticket==0 || !OrderSelect(ticket)) continue;
         if(OrderGetString(ORDER_SYMBOL)!=FRANZ_SYMBOL ||
            OrderGetInteger(ORDER_MAGIC)!=FRANZ_MAGIC ||
            !OwnComment(OrderGetString(ORDER_COMMENT))) continue;
         const ENUM_ORDER_TYPE type=(ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
         if(type!=ORDER_TYPE_BUY_LIMIT && type!=ORDER_TYPE_SELL_LIMIT) continue;
         const int size=ArraySize(tickets);
         ArrayResize(tickets,size+1);
         tickets[size]=ticket;
        }
      return ArraySize(tickets);
     }

   ulong TicketByComment(const string comment) const
     {
      for(int index=PositionsTotal()-1;index>=0;index--)
        {
         const ulong ticket=PositionGetTicket(index);
         if(ticket==0 || !PositionSelectByTicket(ticket)) continue;
         if(PositionGetString(POSITION_SYMBOL)==FRANZ_SYMBOL &&
            PositionGetInteger(POSITION_MAGIC)==FRANZ_MAGIC &&
            PositionGetString(POSITION_COMMENT)==comment) return ticket;
        }
      return 0;
     }

   bool SaveState(const string failure_reason="STATE_SAVE_FAILED")
     {
      if(m_store.Save(m_state)) return true;
      m_authority=false;
      m_data_healthy=false;
      m_state.state=FRANZ_STATE_FAILED;
      m_audit.Emit("ENGINE_ERROR",TimeTradeServer(),m_state,failure_reason);
      return false;
     }

   void Transition(const FranzState state,const string reason)
     {
      m_state.state=state;
      m_state.close_reason=reason;
      SaveState();
      m_audit.Emit("STATE_TRANSITION",TimeTradeServer(),m_state,reason);
     }

   void ClearSetup(const FranzState terminal_state,const string reason)
     {
      m_state.state=terminal_state;
      m_state.close_reason=reason;
      m_state.cooldown_until=TimeTradeServer()+3600;
      SaveState();
      m_audit.Emit("SETUP_TERMINAL",TimeTradeServer(),m_state,reason);
     }

   void ResetDayIfSafe(const datetime server_time)
     {
      const int key=ServerDayKey(server_time);
      if(m_state.day_key==key) return;
      ulong positions[];
      if(OwnPositions(positions)>0) return;
      const datetime last_m15=m_state.last_m15_close;
      const datetime last_m5=m_state.last_m5_close;
      const datetime last_m1=m_state.last_m1_close;
      FranzResetPersistentState(m_state);
      m_state.state=FRANZ_STATE_IDLE;
      m_state.day_key=key;
      m_state.last_m15_close=last_m15;
      m_state.last_m5_close=last_m5;
      m_state.last_m1_close=last_m1;
      SaveState();
     }

   double AheadObstacle(const FranzBar &bars[],const FranzSide side,const double entry) const
     {
      double result=0.0,distance=DBL_MAX;
      for(int index=2;index<ArraySize(bars)-2;index++)
        {
         const bool valid=(side==FRANZ_SIDE_BUY ? FranzPivotHigh(bars,index) :
                                                    FranzPivotLow(bars,index));
         if(!valid) continue;
         const double candidate=(side==FRANZ_SIDE_BUY ? bars[index].high : bars[index].low);
         const bool ahead=(side==FRANZ_SIDE_BUY ? candidate>entry : candidate<entry);
         if(!ahead) continue;
         const double current=MathAbs(candidate-entry);
         if(current<distance) { distance=current; result=candidate; }
        }
      return result;
     }

   double ZoneDistance(const FranzSwingZone &zone,const double price) const
     {
      if(!zone.valid) return DBL_MAX;
      const double lower=MathMin(zone.proximal,zone.distal);
      const double upper=MathMax(zone.proximal,zone.distal);
      if(price<lower) return lower-price;
      if(price>upper) return price-upper;
      return 0.0;
     }

   FranzSwingZone NearestOrMergedZone(const FranzSwingZone &first,
                                      const FranzSwingZone &second,
                                      const double price,
                                      const double median_range) const
     {
      FranzSwingZone result;
      FranzResetSwingZone(result);
      if(FranzMergeSwingZones(first,second,median_range,result)) return result;
      if(!first.valid) return second;
      if(!second.valid) return first;
      return ZoneDistance(first,price)<=ZoneDistance(second,price) ? first : second;
     }

   bool FindTwoSweepRsi(const FranzBar &bars[],const double &rsi[],
                        double &previous_price,double &current_price,
                        double &previous_rsi,double &current_rsi) const
     {
      int first=-1,second=-1;
      for(int index=0;index<MathMin(ArraySize(bars),ArraySize(rsi));index++)
        {
         const bool qualifies=(m_state.side==FRANZ_SIDE_SELL ?
            bars[index].high>=m_state.liquidity_reference :
            bars[index].low<=m_state.liquidity_reference);
         if(!qualifies) continue;
         if(first<0) first=index;
         else if(MathAbs(index-first)>=2) { second=index; break; }
        }
      if(first<0 || second<0) return false;
      current_price=(m_state.side==FRANZ_SIDE_SELL ? bars[first].high : bars[first].low);
      previous_price=(m_state.side==FRANZ_SIDE_SELL ? bars[second].high : bars[second].low);
      current_rsi=rsi[first];
      previous_rsi=rsi[second];
      return true;
     }

   int CurrentRsiVotes(const FranzBar &m1[],bool &stochastic_reinforced) const
     {
      double rsi_m1[],rsi_m5[],k[],d[];
      if(!CopyIndicator(m_rsi_m1,0,12,rsi_m1) ||
         !CopyIndicator(m_rsi_m5,0,3,rsi_m5) ||
         !CopyIndicator(m_stochastic_m1,0,4,k) ||
         !CopyIndicator(m_stochastic_m1,1,4,d)) return -1;
      double previous_price=m_state.liquidity_reference;
      double current_price=m_state.sweep_extreme;
      double previous_rsi=rsi_m1[MathMin(5,ArraySize(rsi_m1)-1)];
      double current_rsi=rsi_m1[1];
      FindTwoSweepRsi(m1,rsi_m1,previous_price,current_price,previous_rsi,current_rsi);
      stochastic_reinforced=m_use_stochastic && FranzStochasticReinforced(
         m_state.side,k[0],d[0],k[1],d[1],k[2],k[1]);
      if(!m_use_rsi) return 3;
      return FranzRsiVotes(m_state.side,previous_price,current_price,
         previous_rsi,current_rsi,rsi_m1[0],rsi_m1[1],rsi_m1[2],
         rsi_m5[0],rsi_m5[2]);
     }

   bool RegimeStillAligned(void) const
     {
      FranzBar d1[],h4[],h1[];
      if(!LoadBars(PERIOD_D1,80,d1) || !LoadBars(PERIOD_H4,80,h4) ||
         !LoadBars(PERIOD_H1,80,h1)) return false;
      const int required=(m_state.side==FRANZ_SIDE_BUY ? 1 : -1);
      return FranzSwingDirection(d1)==required &&
             FranzSwingDirection(h4)==required &&
             FranzSwingDirection(h1)==required;
     }

   bool CreateSetupFromM15(const MqlTick &tick)
     {
      if(m_state.state==FRANZ_STATE_DAILY_LOCKED ||
         m_state.daily_setups>=3 || tick.time<m_state.cooldown_until)
         return false;
      ulong positions[];
      if(OwnPositions(positions)>0) return false;
      if(m_state.state!=FRANZ_STATE_IDLE && m_state.state!=FRANZ_STATE_CLOSED &&
         m_state.state!=FRANZ_STATE_EXPIRED && m_state.state!=FRANZ_STATE_CANCELLED &&
         m_state.state!=FRANZ_STATE_FAILED) return false;

      FranzBar m15[],m30[],h1[],h4[],d1[];
      if(!LoadBars(PERIOD_M15,260,m15) || !LoadBars(PERIOD_M30,130,m30) ||
         !LoadBars(PERIOD_H1,80,h1) || !LoadBars(PERIOD_H4,80,h4) ||
         !LoadBars(PERIOD_D1,80,d1)) return false;
      FranzSide side;
      double anchor_a=0.0,extreme_b=0.0,median_range=0.0;
      int impulse_bars=0;
      bool terminal_wick=false;
      string reason="";
      if(!FranzEvaluateImpulse(m15,side,anchor_a,extreme_b,median_range,
                               impulse_bars,terminal_wick,reason)) return false;
      const double body_ratio=FranzRange(m15[0])>0.0 ?
         FranzBody(m15[0])/FranzRange(m15[0]) : 0.0;
      const bool terminal_close=(side==FRANZ_SIDE_SELL ?
         m15[0].close>=m15[0].low+0.80*FranzRange(m15[0]) :
         m15[0].close<=m15[0].low+0.20*FranzRange(m15[0]));
      if(body_ratio>=0.70 && terminal_close) return false;

      const double efficiency=FranzEfficiencyRatio(h1,12);
      const FranzMode mode=FranzSelectMode(
         FranzSwingDirection(d1),FranzSwingDirection(h4),
         FranzSwingDirection(h1),side,efficiency);
      if(mode==FRANZ_MODE_NONE) return false;
      FranzTrendlineZone bull_zone,bear_zone;
      if(!FranzBuildTrendlineZone(m15,true,tick.time,median_range,
                                  tick.ask-tick.bid,bull_zone) ||
         !FranzBuildTrendlineZone(m15,false,tick.time,median_range,
                                  tick.ask-tick.bid,bear_zone)) return false;
      if(FranzProjectTrendline(bull_zone,tick.time)>=
         FranzProjectTrendline(bear_zone,tick.time)) return false;

      FranzSwingZone supply_m15,supply_m30,demand_m15,demand_m30;
      FranzFindSwingZone(m15,true,extreme_b,supply_m15);
      FranzFindSwingZone(m30,true,extreme_b,supply_m30);
      FranzFindSwingZone(m15,false,extreme_b,demand_m15);
      FranzFindSwingZone(m30,false,extreme_b,demand_m30);
      const FranzSwingZone supply_zone=NearestOrMergedZone(
         supply_m15,supply_m30,extreme_b,median_range);
      const FranzSwingZone demand_zone=NearestOrMergedZone(
         demand_m15,demand_m30,extreme_b,median_range);
      const FranzSwingZone active_zone=(side==FRANZ_SIDE_SELL ? supply_zone : demand_zone);
      if(!active_zone.valid || active_zone.invalidated ||
         !FranzPriceInSwingZone(active_zone,extreme_b,0.25*median_range))
         return false;
      const double reference=active_zone.distal;

      m_state.state=FRANZ_STATE_EXTREME_WATCH;
      m_state.mode=mode;
      m_state.side=side;
      m_state.setup_id=CompactSetupId(tick.time,side);
      m_state.setup_created_at=tick.time;
      m_state.setup_expires_at=tick.time+60*60;
      m_state.watch_m1_bars=0;
      m_state.break_m1_bars=0;
      m_state.fib_m1_bars=0;
      m_state.liquidity_reference=reference;
      m_state.sweep_extreme=extreme_b;
      m_state.bull_zone=bull_zone;
      m_state.bear_zone=bear_zone;
      m_state.supply_zone=supply_zone;
      m_state.demand_zone=demand_zone;
      m_state.initial_trendline_break=false;
      m_state.initial_break_level=0.0;
      m_state.shakeout_evidence_locked=false;
      m_state.cluster_high=0.0;
      m_state.cluster_low=0.0;
      m_state.rejection_high=0.0;
      m_state.rejection_low=0.0;
      m_state.reentry_closes=0;
      m_state.planned_entry=0.0;
      m_state.stop_loss=0.0;
      m_state.take_profit_1=0.0;
      m_state.take_profit_2=0.0;
      m_state.initial_risk_price=0.0;
      m_state.setup_risk_usd=0.0;
      FranzResetFibonacci(m_state.fibonacci);
      m_state.fibonacci.anchor_a=anchor_a;
      m_state.fibonacci.anchor_b=extreme_b;
      m_state.close_reason=(terminal_wick ? "EXTREME_WICK_REFERENCE_LOCKED" :
                                             "EXTREME_WATCH_CREATED");
      SaveState();
      m_audit.Emit("SETUP_CREATED",tick.time,m_state,m_state.close_reason,
         StringFormat("{\"reference\":%.8f,\"anchor_a\":%.8f,\"extreme_b\":%.8f,"
                      "\"impulse_bars\":%d,\"bull_line\":%.8f,"
                      "\"bear_line\":%.8f,\"supply_proximal\":%.8f,"
                      "\"supply_distal\":%.8f,\"demand_proximal\":%.8f,"
                      "\"demand_distal\":%.8f}",reference,anchor_a,extreme_b,
                      impulse_bars,FranzProjectTrendline(bull_zone,tick.time),
                      FranzProjectTrendline(bear_zone,tick.time),
                      supply_zone.proximal,supply_zone.distal,
                      demand_zone.proximal,demand_zone.distal));
      return true;
     }

   bool BuildEntryDecision(const MqlTick &tick,const FranzBar &m1[],FranzDecision &decision)
     {
      FranzResetDecision(decision);
      decision.state=FRANZ_STATE_ENTRY_READY;
      decision.mode=m_state.mode;
      decision.side=m_state.side;
      decision.setup_id=m_state.setup_id;
      decision.signal_id=m_state.setup_id+"-READY";
      decision.setup_created_at=m_state.setup_created_at;
      decision.entry_ready_at=tick.time;
      decision.valid_until=m_state.setup_expires_at;
      decision.fibonacci=m_state.fibonacci;
      const FranzSwingZone active_zone=(m_state.side==FRANZ_SIDE_SELL ?
         m_state.supply_zone : m_state.demand_zone);
      decision.entry=active_zone.proximal;
      if(m_use_fibonacci_gate && !FranzPriceWithinFibEntry(
            m_state.side,m_state.fibonacci,decision.entry)) return false;
      decision.stop_loss=FranzStructuralStop(m_state.side,m_state.fibonacci,
         m_state.sweep_extreme,tick.ask-tick.bid,0.01);
      FranzBar m5[],m15[];
      if(!LoadBars(PERIOD_M5,64,m5) || !LoadBars(PERIOD_M15,64,m15)) return false;
      if(m_state.mode==FRANZ_MODE_HANDGUN_RANGE)
        {
         double obstacle=AheadObstacle(m1,m_state.side,decision.entry);
         const double m5_obstacle=AheadObstacle(m5,m_state.side,decision.entry);
         if(m5_obstacle>0.0 && (obstacle==0.0 ||
            MathAbs(m5_obstacle-decision.entry)<MathAbs(obstacle-decision.entry)))
            obstacle=m5_obstacle;
         const FranzSwingZone opposing=(m_state.side==FRANZ_SIDE_BUY ?
            m_state.supply_zone : m_state.demand_zone);
         const double zone_obstacle=(m_state.side==FRANZ_SIDE_BUY ?
            MathMin(opposing.proximal,opposing.distal) :
            MathMax(opposing.proximal,opposing.distal));
         if(opposing.valid && (obstacle==0.0 ||
            MathAbs(zone_obstacle-decision.entry)<MathAbs(obstacle-decision.entry)))
            obstacle=zone_obstacle;
         decision.take_profit_1=FranzTargetBeforeObstacle(m_state.side,
            m_state.fibonacci.level_500,obstacle,decision.entry,0.01);
         decision.take_profit_2=decision.take_profit_1;
        }
      else
        {
         const double obstacle=AheadObstacle(m15,m_state.side,decision.entry);
         const FranzSwingZone opposing=(m_state.side==FRANZ_SIDE_BUY ?
            m_state.supply_zone : m_state.demand_zone);
         const double zone_obstacle=(m_state.side==FRANZ_SIDE_BUY ?
            MathMin(opposing.proximal,opposing.distal) :
            MathMax(opposing.proximal,opposing.distal));
         double first_obstacle=obstacle;
         if(opposing.valid && (first_obstacle==0.0 ||
            MathAbs(zone_obstacle-decision.entry)<MathAbs(first_obstacle-decision.entry)))
            first_obstacle=zone_obstacle;
         decision.take_profit_1=FranzTargetBeforeObstacle(m_state.side,
            m_state.fibonacci.level_618,first_obstacle,decision.entry,0.01);
         decision.take_profit_2=m_state.fibonacci.level_1000;
        }
      decision.projected_r_1=FranzProjectedR(m_state.side,decision.entry,
         decision.stop_loss,decision.take_profit_1);
      decision.projected_r_2=FranzProjectedR(m_state.side,decision.entry,
         decision.stop_loss,decision.take_profit_2);
      if(m_state.mode==FRANZ_MODE_HANDGUN_RANGE && decision.projected_r_1<1.25)
         return false;
      if(m_state.mode==FRANZ_MODE_SNIPER_TREND &&
         (decision.projected_r_1<1.25 || decision.projected_r_2<2.0)) return false;
      decision.reason="ENTRY_GEOMETRY_VALID";
      return true;
     }

   ENUM_ORDER_TYPE_FILLING FillingMode(void) const
     {
      const int allowed=(int)SymbolInfoInteger(FRANZ_SYMBOL,SYMBOL_FILLING_MODE);
      if((allowed&SYMBOL_FILLING_IOC)==SYMBOL_FILLING_IOC) return ORDER_FILLING_IOC;
      return ORDER_FILLING_FOK;
     }

   bool CheckPendingOrder(const FranzSide side,const double volume,
                          const double price,const double sl,const double tp,
                          const datetime expires,MqlTradeCheckResult &check,
                          string &reason) const
     {
      MqlTradeRequest request;
      ZeroMemory(request);
      ZeroMemory(check);
      request.action=TRADE_ACTION_PENDING;
      request.magic=FRANZ_MAGIC;
      request.symbol=FRANZ_SYMBOL;
      request.volume=volume;
      request.type=(side==FRANZ_SIDE_BUY ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT);
      request.price=price;
      request.sl=sl;
      request.tp=tp;
      request.deviation=30;
      request.type_filling=ORDER_FILLING_RETURN;
      request.type_time=ORDER_TIME_SPECIFIED;
      request.expiration=expires;
      request.comment="FRZ-CHECK";
      if(!OrderCheck(request,check)) { reason="ORDER_CHECK_CALL_FAILED"; return false; }
      if(check.retcode!=0 && check.retcode!=TRADE_RETCODE_DONE &&
         check.retcode!=TRADE_RETCODE_PLACED)
        { reason="ORDER_CHECK_REJECTED"; return false; }
      reason="ORDER_CHECK_OK";
      return true;
     }

   bool DeleteOrder(const ulong ticket)
     {
      if(ticket==0 || !OrderSelect(ticket)) return true;
      if(OrderGetString(ORDER_SYMBOL)!=FRANZ_SYMBOL ||
         OrderGetInteger(ORDER_MAGIC)!=FRANZ_MAGIC ||
         !OwnComment(OrderGetString(ORDER_COMMENT))) return false;
      const bool sent=m_trade.OrderDelete(ticket);
      return sent && TradeRetcodeOk();
     }

   bool DeleteAllOwnOrders(void)
     {
      ulong tickets[];
      OwnOrders(tickets);
      bool ok=true;
      for(int index=0;index<ArraySize(tickets);index++)
         if(!DeleteOrder(tickets[index])) ok=false;
      return ok;
     }

   bool CloseTicket(const ulong ticket)
     {
      if(ticket==0 || !PositionSelectByTicket(ticket)) return true;
      if(PositionGetString(POSITION_SYMBOL)!=FRANZ_SYMBOL ||
         PositionGetInteger(POSITION_MAGIC)!=FRANZ_MAGIC ||
         !OwnComment(PositionGetString(POSITION_COMMENT))) return false;
      const bool sent=m_trade.PositionClose(ticket,30);
      return sent && TradeRetcodeOk();
     }

   bool CloseAllOwn(const string reason)
     {
      ulong tickets[];
      OwnPositions(tickets);
      bool ok=true;
      for(int index=0;index<ArraySize(tickets);index++)
         if(!CloseTicket(tickets[index])) ok=false;
      if(ArraySize(tickets)>0)
        {
         m_state.state=FRANZ_STATE_EXIT_PENDING;
         m_state.close_reason=reason;
         m_state.cleanup_started_ms=GetTickCount64();
         m_state.cleanup_attempts=1;
         SaveState();
        }
      return ok;
     }

   double HistoricalPositionResult(const ulong position_id) const
     {
      if(position_id==0 || !HistorySelectByPosition(position_id)) return 0.0;
      double total=0.0;
      for(int index=0;index<HistoryDealsTotal();index++)
        {
         const ulong deal=HistoryDealGetTicket(index);
         if(deal==0 || HistoryDealGetString(deal,DEAL_SYMBOL)!=FRANZ_SYMBOL)
            continue;
         total+=HistoryDealGetDouble(deal,DEAL_PROFIT)+
                HistoryDealGetDouble(deal,DEAL_SWAP)+
                HistoryDealGetDouble(deal,DEAL_COMMISSION)+
                HistoryDealGetDouble(deal,DEAL_FEE);
        }
      return total;
     }

   bool HistoricalPositionClosedByTp(const ulong position_id) const
     {
      if(position_id==0 || !HistorySelectByPosition(position_id)) return false;
      for(int index=HistoryDealsTotal()-1;index>=0;index--)
        {
         const ulong deal=HistoryDealGetTicket(index);
         if(deal==0) continue;
         const ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(
            deal,DEAL_ENTRY);
         if((entry==DEAL_ENTRY_OUT || entry==DEAL_ENTRY_OUT_BY) &&
            (ENUM_DEAL_REASON)HistoryDealGetInteger(deal,DEAL_REASON)==DEAL_REASON_TP)
            return true;
        }
      return false;
     }

   bool SubmitDecision(const FranzDecision &decision,const MqlTick &tick,string &reason)
     {
      if(!m_authority) { reason="TESTER_ORDER_AUTHORITY_DISABLED"; return false; }
      if(tick.ask-tick.bid>0.60) { reason="SPREAD_TOO_WIDE"; return false; }
      ulong existing[],orders[];
      if(OwnPositions(existing)>0 || OwnOrders(orders)>0)
        { reason="OWN_EXPOSURE_ALREADY_EXISTS"; return false; }
      const int legs=(decision.mode==FRANZ_MODE_SNIPER_TREND ? 2 : 1);
      const double risk_price=MathAbs(decision.entry-decision.stop_loss);
      const double setup_loss=risk_price*100.0*0.01*legs;
      const double equity=AccountInfoDouble(ACCOUNT_EQUITY);
      const double budget=MathMin(0.10*equity,MathMax(0.0,equity-4.0));
      if(setup_loss<=0.0 || setup_loss>budget)
        { reason="PLANNED_LOSS_EXCEEDS_BUDGET"; return false; }
      const double minimum_distance=MathMax(
         SymbolInfoInteger(FRANZ_SYMBOL,SYMBOL_TRADE_STOPS_LEVEL),
         SymbolInfoInteger(FRANZ_SYMBOL,SYMBOL_TRADE_FREEZE_LEVEL))*
         SymbolInfoDouble(FRANZ_SYMBOL,SYMBOL_POINT);
      if((decision.side==FRANZ_SIDE_BUY && decision.entry>=tick.ask-minimum_distance) ||
         (decision.side==FRANZ_SIDE_SELL && decision.entry<=tick.bid+minimum_distance))
        { reason="LIMIT_ENTRY_ALREADY_PASSED"; return false; }
      MqlTradeCheckResult first_check,second_check;
      if(!CheckPendingOrder(decision.side,0.01,decision.entry,decision.stop_loss,
            decision.take_profit_1,decision.valid_until,first_check,reason)) return false;
      if(legs==2 && !CheckPendingOrder(decision.side,0.01,decision.entry,
            decision.stop_loss,decision.take_profit_2,decision.valid_until,
            second_check,reason)) return false;
      const double required_margin=first_check.margin+(legs==2 ? second_check.margin : 0.0);
      if(required_margin>AccountInfoDouble(ACCOUNT_MARGIN_FREE))
        { reason="PAIR_MARGIN_INSUFFICIENT"; return false; }

      const bool first_sent=(decision.side==FRANZ_SIDE_BUY ?
         m_trade.BuyLimit(0.01,decision.entry,FRANZ_SYMBOL,decision.stop_loss,
            decision.take_profit_1,ORDER_TIME_SPECIFIED,decision.valid_until,
            LegComment(1)) :
         m_trade.SellLimit(0.01,decision.entry,FRANZ_SYMBOL,decision.stop_loss,
            decision.take_profit_1,ORDER_TIME_SPECIFIED,decision.valid_until,
            LegComment(1)));
      if(!first_sent || !TradeRetcodeOk())
        { reason="LEG1_SUBMIT_FAILED"; return false; }
      m_state.leg1_ticket=m_trade.ResultOrder();
      if(m_state.leg1_ticket==0)
        { reason="LEG1_CAPTURE_FAILED"; DeleteAllOwnOrders(); return false; }

      if(legs==2)
        {
         const bool second_sent=(decision.side==FRANZ_SIDE_BUY ?
            m_trade.BuyLimit(0.01,decision.entry,FRANZ_SYMBOL,decision.stop_loss,
               decision.take_profit_2,ORDER_TIME_SPECIFIED,decision.valid_until,
               LegComment(2)) :
            m_trade.SellLimit(0.01,decision.entry,FRANZ_SYMBOL,decision.stop_loss,
               decision.take_profit_2,ORDER_TIME_SPECIFIED,decision.valid_until,
               LegComment(2)));
         if(!second_sent || !TradeRetcodeOk())
           {
            reason="LEG2_SUBMIT_FAILED";
            DeleteOrder(m_state.leg1_ticket);
            m_state.state=FRANZ_STATE_FAILED;
            SaveState();
            m_audit.Emit("ENGINE_ERROR",tick.time,m_state,reason);
            return false;
           }
         m_state.leg2_ticket=m_trade.ResultOrder();
         if(m_state.leg2_ticket==0)
           {
            reason="LEG2_CAPTURE_FAILED";
            DeleteAllOwnOrders();
            m_state.state=FRANZ_STATE_FAILED;
            SaveState();
            return false;
           }
        }

      m_state.state=FRANZ_STATE_ENTRY_READY;
      m_state.planned_entry=decision.entry;
      m_state.stop_loss=decision.stop_loss;
      m_state.take_profit_1=decision.take_profit_1;
      m_state.take_profit_2=decision.take_profit_2;
      m_state.initial_risk_price=risk_price;
      m_state.setup_risk_usd=setup_loss;
      m_state.position_opened_at=0;
      m_state.leg1_closed=false;
      m_state.leg2_closed=(legs==1);
      m_state.tp1_hit=false;
      m_state.setup_realized_pnl=0.0;
      SaveState();
      m_audit.Emit("LIMIT_ORDERS_PLACED",tick.time,m_state,"LIMIT_ORDERS_PLACED",
         StringFormat("{\"entry\":%.8f,\"sl\":%.8f,\"tp1\":%.8f,"
                      "\"tp2\":%.8f,\"legs\":%d}",decision.entry,
                      decision.stop_loss,decision.take_profit_1,
                      decision.take_profit_2,legs));
      reason="LIMIT_ORDERS_PLACED";
      return true;
     }

   bool ProtectSecondLeg(void)
     {
      if(m_state.mode!=FRANZ_MODE_SNIPER_TREND || m_state.leg2_ticket==0 ||
         !PositionSelectByTicket(m_state.leg2_ticket)) return true;
      const double risk=m_state.initial_risk_price;
      double protected_sl=(m_state.side==FRANZ_SIDE_BUY ?
         MathMax(m_state.planned_entry+0.10*risk,m_state.fibonacci.level_382) :
         MathMin(m_state.planned_entry-0.10*risk,m_state.fibonacci.level_382));
      protected_sl=(m_state.side==FRANZ_SIDE_BUY ? FranzAlignDown(protected_sl,0.01) :
                                                  FranzAlignUp(protected_sl,0.01));
      double target=m_state.take_profit_2;
      if(RegimeStillAligned())
        {
         FranzBar m15[];
         if(LoadBars(PERIOD_M15,64,m15))
           {
            const double obstacle=AheadObstacle(m15,m_state.side,m_state.fibonacci.level_1000);
            const bool clear=(obstacle<=0.0 ||
               (m_state.side==FRANZ_SIDE_BUY ? obstacle>=m_state.fibonacci.level_1272 :
                                               obstacle<=m_state.fibonacci.level_1272));
            if(clear) target=m_state.fibonacci.level_1272;
           }
        }
      const bool sent=m_trade.PositionModify(m_state.leg2_ticket,protected_sl,target);
      if(sent && TradeRetcodeOk())
        {
         m_state.stop_loss=protected_sl;
         m_state.take_profit_2=target;
         m_state.cleanup_attempts=0;
         m_state.cleanup_started_ms=0;
         SaveState();
         m_audit.Emit("TP2_PROTECTED",TimeTradeServer(),m_state,"TP1_HIT");
         return true;
        }
      if(m_state.cleanup_started_ms==0) m_state.cleanup_started_ms=GetTickCount64();
      m_state.cleanup_attempts++;
      SaveState();
      return false;
     }

   void FinalizeClosedSetup(const datetime server_time)
     {
      if(m_state.state==FRANZ_STATE_CLOSED ||
         m_state.state==FRANZ_STATE_DAILY_LOCKED) return;
      m_state.setup_realized_pnl=
         HistoricalPositionResult(m_state.leg1_position_id)+
         HistoricalPositionResult(m_state.leg2_position_id);
      const double result_r=(m_state.setup_risk_usd>0.0 ?
         m_state.setup_realized_pnl/m_state.setup_risk_usd : 0.0);
      m_state.daily_r+=result_r;
      m_state.cooldown_until=server_time+3600;
      m_state.state=(m_state.daily_r<=-2.0 || m_state.daily_r>=3.0 ?
         FRANZ_STATE_DAILY_LOCKED : FRANZ_STATE_CLOSED);
      m_state.close_reason="SETUP_CLOSED";
      m_audit.Emit("POSITION_CLOSED",server_time,m_state,"SETUP_CLOSED",
         StringFormat("{\"profit_loss\":%.8f,\"result_r\":%.8f,"
                      "\"daily_r\":%.8f,\"balance\":%.2f,\"equity\":%.2f}",
                      m_state.setup_realized_pnl,result_r,m_state.daily_r,
                      AccountInfoDouble(ACCOUNT_BALANCE),AccountInfoDouble(ACCOUNT_EQUITY)));
      m_state.leg1_ticket=0;
      m_state.leg2_ticket=0;
      m_state.leg1_position_id=0;
      m_state.leg2_position_id=0;
      SaveState();
     }

   void ManagePendingEntry(const MqlTick &tick)
     {
      if(m_state.state!=FRANZ_STATE_ENTRY_READY) return;
      ulong positions[],orders[];
      const int position_count=OwnPositions(positions);
      const int order_count=OwnOrders(orders);
      const int expected=(m_state.mode==FRANZ_MODE_SNIPER_TREND ? 2 : 1);
      if(tick.time>=m_state.setup_expires_at)
        {
         DeleteAllOwnOrders();
         if(position_count>0) CloseAllOwn("PARTIAL_FILL_AT_EXPIRY");
         else ClearSetup(FRANZ_STATE_EXPIRED,"LIMIT_ENTRY_EXPIRED");
         return;
        }
      if(position_count==0 && order_count==expected) return;
      if(position_count==expected && order_count==0)
        {
         m_state.leg1_ticket=TicketByComment(LegComment(1));
         m_state.leg2_ticket=(expected==2 ? TicketByComment(LegComment(2)) : 0);
         if(m_state.leg1_ticket==0 || (expected==2 && m_state.leg2_ticket==0))
           {
            CloseAllOwn("FILLED_POSITION_CAPTURE_FAILED");
            m_state.state=FRANZ_STATE_FAILED;
            SaveState();
            return;
           }
         if(PositionSelectByTicket(m_state.leg1_ticket))
            m_state.leg1_position_id=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
         if(expected==2 && PositionSelectByTicket(m_state.leg2_ticket))
            m_state.leg2_position_id=(ulong)PositionGetInteger(POSITION_IDENTIFIER);
         m_state.state=FRANZ_STATE_POSITION_OPEN;
         m_state.position_opened_at=tick.time;
         m_state.daily_setups++;
         m_state.cleanup_attempts=0;
         m_state.cleanup_started_ms=0;
         SaveState();
         m_audit.Emit("POSITION_OPENED",tick.time,m_state,"LIMIT_ENTRY_FILLED",
            StringFormat("{\"entry\":%.8f,\"sl\":%.8f,\"tp1\":%.8f,"
                         "\"tp2\":%.8f,\"legs\":%d}",m_state.planned_entry,
                         m_state.stop_loss,m_state.take_profit_1,
                         m_state.take_profit_2,expected));
         return;
        }
      if(m_state.cleanup_started_ms==0)
        {
         m_state.cleanup_started_ms=GetTickCount64();
         SaveState();
         return;
        }
      if(GetTickCount64()-m_state.cleanup_started_ms<250) return;
      DeleteAllOwnOrders();
      if(position_count>0) CloseAllOwn("ATOMIC_LIMIT_FILL_FAILED");
      else
        {
         m_state.state=FRANZ_STATE_FAILED;
         m_state.close_reason="PENDING_ORDER_COUNT_MISMATCH";
         SaveState();
        }
      m_audit.Emit("ENGINE_ERROR",tick.time,m_state,m_state.close_reason);
     }

   void ManageOpenPositions(const MqlTick &tick)
     {
      if(m_state.state!=FRANZ_STATE_POSITION_OPEN &&
         m_state.state!=FRANZ_STATE_EXIT_PENDING) return;
      ulong positions[];
      const int count=OwnPositions(positions);
      if(count==0)
        {
         if(m_state.state==FRANZ_STATE_POSITION_OPEN)
           {
            m_state.state=FRANZ_STATE_EXIT_PENDING;
            m_state.close_reason="WAITING_FOR_CLOSE_DEALS";
            m_state.cleanup_started_ms=GetTickCount64();
            SaveState();
           }
         return;
        }
      const int maximum_seconds=(m_state.mode==FRANZ_MODE_HANDGUN_RANGE ? 15*60 : 4*3600);
      if(m_state.position_opened_at>0 && tick.time-m_state.position_opened_at>=maximum_seconds)
         CloseAllOwn("MAXIMUM_HOLD_REACHED");
     }

   bool LockShakeoutEvidence(const FranzBar &m1[],const MqlTick &tick)
     {
      if(m_state.shakeout_evidence_locked) return true;
      int touches=0,changes=0;
      double high=0.0,low=0.0,sweep=0.0;
      const FranzSwingZone active_zone=(m_state.side==FRANZ_SIDE_SELL ?
         m_state.supply_zone : m_state.demand_zone);
      if(!FranzClusterEvidence(m1,m_state.side,active_zone.proximal,
           active_zone.distal,
           0.25*FranzMedianTrueRange(m1,0,20),0.01,touches,changes,
           high,low,sweep)) return false;
      m_state.cluster_high=high;
      m_state.cluster_low=low;
      m_state.sweep_extreme=sweep;
      int sweep_index=0;
      for(int index=0;index<12;index++)
        {
         const double candidate=(m_state.side==FRANZ_SIDE_SELL ?
            m1[index].high : m1[index].low);
         if(MathAbs(candidate-sweep)<=0.005) { sweep_index=index; break; }
        }
      m_state.rejection_high=m1[sweep_index].high;
      m_state.rejection_low=m1[sweep_index].low;
      m_state.shakeout_evidence_locked=true;
      SaveState();
      m_audit.Emit("SHAKEOUT_EVIDENCE_LOCKED",tick.time,m_state,
         "SHAKEOUT_EVIDENCE_LOCKED",StringFormat(
            "{\"touches\":%d,\"direction_changes\":%d,"
            "\"cluster_high\":%.8f,\"cluster_low\":%.8f,"
            "\"sweep_extreme\":%.8f}",touches,changes,high,low,sweep));
      return true;
     }

   void ProcessM15(const MqlTick &tick)
     {
      const datetime latest=tick.time-(tick.time%PeriodSeconds(PERIOD_M15));
      if(latest<=0 || latest<=m_state.last_m15_close) return;
      m_state.last_m15_close=latest;
      CreateSetupFromM15(tick);
     }

   void ProcessM1(const MqlTick &tick)
     {
      const datetime latest=tick.time-(tick.time%PeriodSeconds(PERIOD_M1));
      if(latest<=0 || latest<=m_state.last_m1_close) return;
      m_state.last_m1_close=latest;
      ResetDayIfSafe(tick.time);
      if(m_state.state!=FRANZ_STATE_EXTREME_WATCH &&
         m_state.state!=FRANZ_STATE_TRENDLINE_BREAK_SIGN &&
         m_state.state!=FRANZ_STATE_BREAK_ATTEMPT &&
         m_state.state!=FRANZ_STATE_SHAKEOUT_CONFIRMED &&
         m_state.state!=FRANZ_STATE_FIB_RECLAIMED) return;
      FranzBar m1[];
      if(!LoadBars(PERIOD_M1,40,m1)) return;
      if(tick.time>=m_state.setup_expires_at)
        { ClearSetup(FRANZ_STATE_EXPIRED,"SETUP_VALIDITY_EXPIRED"); return; }

      if(m_state.state==FRANZ_STATE_EXTREME_WATCH)
        {
         m_state.watch_m1_bars++;
         if(tick.time>=m_state.setup_expires_at || m_state.watch_m1_bars>60)
           { ClearSetup(FRANZ_STATE_EXPIRED,"SHAKEOUT_EXPIRED"); return; }
         LockShakeoutEvidence(m1,tick);
         FranzTrendlineZone micro_bull,micro_bear;
         FranzBar m5_break[];
         if(!LoadBars(PERIOD_M5,64,m5_break)) return;
         const double m5_median=FranzMedianTrueRange(m5_break,0,20);
         if(!FranzBuildTrendlineZone(m5_break,true,m5_break[0].close_time,m5_median,
                                     tick.ask-tick.bid,micro_bull) ||
            !FranzBuildTrendlineZone(m5_break,false,m5_break[0].close_time,m5_median,
                                     tick.ask-tick.bid,micro_bear)) return;
         double break_level=0.0;
         if(!FranzInitialTrendlineBreak(m_state.side,m5_break[0],m5_break[1],
                                        micro_bull,micro_bear,break_level)) return;
         m_state.initial_trendline_break=true;
         m_state.initial_break_level=break_level;
         m_state.watch_m1_bars=0;
         m_state.setup_expires_at=tick.time+30*60;
         Transition(FRANZ_STATE_TRENDLINE_BREAK_SIGN,
            "INITIAL_TRENDLINE_BREAK_SIGN");
         if(!m_state.shakeout_evidence_locked) return;
         m_state.break_m1_bars=0;
         Transition(FRANZ_STATE_BREAK_ATTEMPT,"BREAK_ATTEMPT_DETECTED");
        }

      if(m_state.state==FRANZ_STATE_TRENDLINE_BREAK_SIGN)
        {
         m_state.watch_m1_bars++;
         if(tick.time>=m_state.setup_expires_at || m_state.watch_m1_bars>30)
           { ClearSetup(FRANZ_STATE_EXPIRED,"POST_BREAK_SHAKEOUT_EXPIRED"); return; }
         if(!LockShakeoutEvidence(m1,tick)) return;
         m_state.break_m1_bars=0;
         Transition(FRANZ_STATE_BREAK_ATTEMPT,"BREAK_ATTEMPT_DETECTED");
        }

      if(m_state.state==FRANZ_STATE_BREAK_ATTEMPT)
        {
         m_state.break_m1_bars++;
         if(m_state.break_m1_bars>3)
           { ClearSetup(FRANZ_STATE_EXPIRED,"BREAK_FAILURE_EXPIRED"); return; }
         bool stochastic=false;
         const int rsi_votes=CurrentRsiVotes(m1,stochastic);
         if(rsi_votes<0) return;
         int reentries=0;
         bool micro=false,accepted=false;
         string reason="";
         const bool failed=FranzFailedBreakConfirmed(m1,m_state.side,
            m_state.liquidity_reference,m_state.rejection_high,
            m_state.rejection_low,stochastic,reentries,micro,accepted,reason);
         m_state.reentry_closes=reentries;
         if(accepted)
           { ClearSetup(FRANZ_STATE_CANCELLED,"BREAK_ACCEPTED_OUTSIDE"); return; }
         if(!failed) { SaveState(); return; }
         const double anchor_a=m_state.fibonacci.anchor_a;
         if(!FranzComputeFibonacci(m_state.side,anchor_a,m_state.liquidity_reference,
                                   m_state.fibonacci))
           { ClearSetup(FRANZ_STATE_FAILED,"FIBONACCI_LOCK_FAILED"); return; }
         m_state.fib_m1_bars=0;
         m_state.setup_expires_at=tick.time+5*60;
         Transition(FRANZ_STATE_BREAK_FAILED,"BREAK_FAILED_CONFIRMED");
         Transition(FRANZ_STATE_SHAKEOUT_CONFIRMED,
            stochastic ? "SHAKEOUT_STOCH_REINFORCED" : "SHAKEOUT_TWO_REENTRIES");
        }

      if(m_state.state==FRANZ_STATE_SHAKEOUT_CONFIRMED)
        {
         m_state.fib_m1_bars++;
         if(m_state.fib_m1_bars>5)
           { ClearSetup(FRANZ_STATE_EXPIRED,"FIBONACCI_ENTRY_EXPIRED"); return; }
         if(FranzPassedHalfBeforeEntry(m_state.side,m_state.fibonacci,m1[0].close))
           { ClearSetup(FRANZ_STATE_CANCELLED,"FIBONACCI_HALF_PASSED"); return; }
         bool stochastic=false;
         const int votes=CurrentRsiVotes(m1,stochastic);
         if(votes<0 || (m_use_rsi && votes<2)) return;
         m_state.fib_m1_bars=0;
         Transition(FRANZ_STATE_FIB_RECLAIMED,"FIBONACCI_GEOMETRY_LOCKED");
        }

      if(m_state.state==FRANZ_STATE_FIB_RECLAIMED)
        {
         m_state.fib_m1_bars++;
         if(m_state.fib_m1_bars>5)
           { ClearSetup(FRANZ_STATE_EXPIRED,"FIBONACCI_RETEST_EXPIRED"); return; }
         if(FranzPassedHalfBeforeEntry(m_state.side,m_state.fibonacci,m1[0].close))
           { ClearSetup(FRANZ_STATE_CANCELLED,"FIBONACCI_HALF_PASSED"); return; }
         bool stochastic=false;
         const int votes=CurrentRsiVotes(m1,stochastic);
         if(votes<0 || (m_use_rsi && votes<2)) return;
         const double entry_tolerance=0.15*FranzMedianTrueRange(m1,0,20);
         const FranzSwingZone active_zone=(m_state.side==FRANZ_SIDE_SELL ?
            m_state.supply_zone : m_state.demand_zone);
         const double planned_limit_entry=active_zone.proximal;
         const bool fibonacci_retest=!m_use_fibonacci_gate ||
            FranzPriceWithinFibEntry(m_state.side,m_state.fibonacci,
                                     planned_limit_entry);
         const bool trendline_retest=m_state.initial_trendline_break;
         const bool swing_zone_touch=FranzPriceInSwingZone(
            active_zone,planned_limit_entry,entry_tolerance);
         const double fib_progress=(m_state.side==FRANZ_SIDE_BUY ?
            (m1[0].close-m_state.fibonacci.anchor_b)/m_state.fibonacci.range :
            (m_state.fibonacci.anchor_b-m1[0].close)/m_state.fibonacci.range);
         m_audit.Emit("ENTRY_GATE_DIAGNOSTIC",tick.time,m_state,
            "FIBONACCI_RETEST_EVALUATED",StringFormat(
               "{\"fib_retest\":%s,\"trendline_retest\":%s,"
               "\"swing_zone_touch\":%s,\"rsi_votes\":%d,"
               "\"stochastic_reinforced\":%s,\"fib_bar\":%d,"
               "\"fib_progress\":%.8f,\"bar_high\":%.8f,"
               "\"bar_low\":%.8f,\"zone_proximal\":%.8f,"
               "\"zone_distal\":%.8f,\"zone_tolerance\":%.8f,"
               "\"planned_limit_entry\":%.8f}",
               fibonacci_retest ? "true" : "false",
               trendline_retest ? "true" : "false",
               swing_zone_touch ? "true" : "false",votes,
               stochastic ? "true" : "false",m_state.fib_m1_bars,
               fib_progress,m1[0].high,m1[0].low,active_zone.proximal,
               active_zone.distal,entry_tolerance,planned_limit_entry));
         if(!fibonacci_retest || !trendline_retest || !swing_zone_touch) return;
         FranzDecision decision;
         if(!BuildEntryDecision(tick,m1,decision))
           {
            m_audit.Emit("ENTRY_GEOMETRY_REJECTED",tick.time,m_state,
               "ENTRY_GEOMETRY_REJECTED",StringFormat(
                  "{\"entry\":%.8f,\"sl\":%.8f,\"tp1\":%.8f,"
                  "\"tp2\":%.8f,\"projected_r1\":%.8f,"
                  "\"projected_r2\":%.8f}",decision.entry,
                  decision.stop_loss,decision.take_profit_1,
                  decision.take_profit_2,decision.projected_r_1,
                  decision.projected_r_2));
            ClearSetup(FRANZ_STATE_CANCELLED,"ENTRY_GEOMETRY_REJECTED");
            return;
           }
         m_state.state=FRANZ_STATE_ENTRY_READY;
         m_state.planned_entry=decision.entry;
         m_state.stop_loss=decision.stop_loss;
         m_state.take_profit_1=decision.take_profit_1;
         m_state.take_profit_2=decision.take_profit_2;
         SaveState();
         string submit_reason="";
         if(!SubmitDecision(decision,tick,submit_reason) &&
            m_state.state!=FRANZ_STATE_FAILED &&
            m_state.state!=FRANZ_STATE_EXIT_PENDING)
            ClearSetup(FRANZ_STATE_CANCELLED,submit_reason);
        }
     }

   bool ReconcileRestart(string &reason)
     {
      ulong positions[],orders[];
      const int count=OwnPositions(positions);
      const int order_count=OwnOrders(orders);
      if(m_state.state==FRANZ_STATE_ENTRY_READY)
        {
         const int expected=(m_state.mode==FRANZ_MODE_SNIPER_TREND ? 2 : 1);
         if(count+order_count!=expected || count>expected || order_count>expected)
           { reason="PENDING_ENTRY_COUNT_AMBIGUOUS"; return false; }
         if(count>0 && order_count>0)
           {
            m_state.cleanup_started_ms=GetTickCount64();
            m_state.cleanup_attempts=0;
           }
         reason="PENDING_ENTRY_RECOVERED";
         return SaveState();
        }
      if(order_count>0)
        { reason="PENDING_ORDER_WITHOUT_ENTRY_STATE"; return false; }
      if(count==0)
        {
         if(m_state.state==FRANZ_STATE_POSITION_OPEN ||
            m_state.state==FRANZ_STATE_EXIT_PENDING)
           {
            m_state.setup_realized_pnl=
               HistoricalPositionResult(m_state.leg1_position_id)+
               HistoricalPositionResult(m_state.leg2_position_id);
            m_state.state=FRANZ_STATE_EXIT_PENDING;
            m_state.cleanup_started_ms=GetTickCount64();
            m_state.cleanup_attempts=0;
            reason="CLOSED_POSITION_RECOVERY_PENDING";
            return SaveState();
           }
         reason="NO_ACTIVE_POSITION";
         return SaveState();
        }
      if(m_state.state!=FRANZ_STATE_POSITION_OPEN &&
         m_state.state!=FRANZ_STATE_EXIT_PENDING)
        { reason="OWN_POSITION_WITHOUT_STATE"; return false; }
      if(count>2 || (m_state.mode==FRANZ_MODE_HANDGUN_RANGE && count>1))
        { reason="POSITION_COUNT_AMBIGUOUS"; return false; }
      m_state.leg1_ticket=TicketByComment(LegComment(1));
      m_state.leg2_ticket=TicketByComment(LegComment(2));
      if(m_state.leg1_ticket==0 && m_state.leg2_ticket==0)
        { reason="POSITION_COMMENT_MISMATCH"; return false; }
      if(m_state.mode==FRANZ_MODE_SNIPER_TREND && count==1)
        {
         if(m_state.leg1_ticket==0 && m_state.leg2_ticket>0)
           {
            m_state.leg1_closed=true;
            m_state.tp1_hit=HistoricalPositionClosedByTp(m_state.leg1_position_id);
            if(!m_state.tp1_hit)
              {
               CloseTicket(m_state.leg2_ticket);
               m_state.state=FRANZ_STATE_EXIT_PENDING;
               m_state.cleanup_started_ms=GetTickCount64();
              }
            else
              {
               m_state.cleanup_started_ms=GetTickCount64();
               m_state.cleanup_attempts=1;
              }
           }
         else if(m_state.leg1_ticket>0 && m_state.leg2_ticket==0)
           {
            CloseTicket(m_state.leg1_ticket);
            m_state.state=FRANZ_STATE_EXIT_PENDING;
            m_state.close_reason="TP2_MISSING_ON_RESTART";
            m_state.cleanup_started_ms=GetTickCount64();
           }
        }
      reason="POSITION_RECOVERED";
      return SaveState();
     }

public:
   CGoldIFranzRuntime(void)
     {
      m_initialized=false;
      m_authority=false;
      m_data_healthy=false;
      m_rsi_m1=INVALID_HANDLE;
      m_rsi_m5=INVALID_HANDLE;
      m_stochastic_m1=INVALID_HANDLE;
      m_use_rsi=true;
      m_use_stochastic=true;
      m_use_fibonacci_gate=true;
      FranzResetPersistentState(m_state);
     }

   int Initialize(const bool tester_authority,
                  const bool use_rsi,
                  const bool use_stochastic,
                  const bool use_fibonacci_gate,
                  const string run_id)
     {
      string reason="";
      if(!ValidateContract(reason))
        { Print("FRANZ_INIT_REJECT reason=",reason); return INIT_FAILED; }
      m_trade.SetExpertMagicNumber(FRANZ_MAGIC);
      m_trade.SetAsyncMode(false);
      m_trade.SetDeviationInPoints(30);
      if(!m_trade.SetTypeFillingBySymbol(FRANZ_SYMBOL)) return INIT_FAILED;
      m_use_rsi=use_rsi;
      m_use_stochastic=use_stochastic;
      m_use_fibonacci_gate=use_fibonacci_gate;
      m_store.Configure(run_id);
      m_audit.Configure(run_id);
      m_rsi_m1=iRSI(FRANZ_SYMBOL,PERIOD_M1,7,PRICE_CLOSE);
      m_rsi_m5=iRSI(FRANZ_SYMBOL,PERIOD_M5,14,PRICE_CLOSE);
      m_stochastic_m1=iStochastic(FRANZ_SYMBOL,PERIOD_M1,5,3,3,MODE_SMA,STO_LOWHIGH);
      if(m_rsi_m1==INVALID_HANDLE || m_rsi_m5==INVALID_HANDLE ||
         m_stochastic_m1==INVALID_HANDLE) return INIT_FAILED;
      const FranzLoadStatus loaded=m_store.Load(m_state);
      if(loaded==FRANZ_LOAD_INVALID)
        { Print("FRANZ_INIT_REJECT reason=STATE_INVALID"); return INIT_FAILED; }
      const datetime now=TimeTradeServer();
      if(loaded==FRANZ_LOAD_MISSING)
        {
         FranzResetPersistentState(m_state);
         m_state.state=FRANZ_STATE_IDLE;
         m_state.day_key=ServerDayKey(now);
         m_state.last_m15_close=iTime(FRANZ_SYMBOL,PERIOD_M15,1)+PeriodSeconds(PERIOD_M15);
         m_state.last_m5_close=iTime(FRANZ_SYMBOL,PERIOD_M5,1)+PeriodSeconds(PERIOD_M5);
         m_state.last_m1_close=iTime(FRANZ_SYMBOL,PERIOD_M1,1)+PeriodSeconds(PERIOD_M1);
         if(!SaveState()) return INIT_FAILED;
        }
      m_authority=tester_authority;
      if(!ReconcileRestart(reason))
        {
         m_authority=false;
         m_state.state=FRANZ_STATE_FAILED;
         m_audit.Emit("ENGINE_ERROR",now,m_state,reason);
         return INIT_FAILED;
        }
      if(!EventSetMillisecondTimer(250)) return INIT_FAILED;
      m_initialized=true;
      m_data_healthy=true;
      m_audit.Emit("ENGINE_STARTED",now,m_state,"WARMUP_COMPLETE",
         StringFormat("{\"authority\":\"%s\",\"rsi\":\"%s\","
                      "\"stochastic\":\"%s\",\"fib_gate\":\"%s\"}",
                      m_authority ? "ENABLED" : "DISABLED",
                      m_use_rsi ? "ENABLED" : "DISABLED",
                      m_use_stochastic ? "ENABLED" : "DISABLED",
                      m_use_fibonacci_gate ? "ENABLED" : "DISABLED"));
      Print("FRANZ_READY authority=",m_authority ? "ENABLED" : "DISABLED");
      return INIT_SUCCEEDED;
     }

   void OnTick(void)
     {
      if(!m_initialized || !m_data_healthy) return;
      MqlTick tick;
      if(!SymbolInfoTick(FRANZ_SYMBOL,tick) || tick.time_msc<=0 || tick.ask<=tick.bid)
        {
         m_authority=false;
         m_data_healthy=false;
         m_state.state=FRANZ_STATE_FAILED;
         m_audit.Emit("ENGINE_ERROR",TimeTradeServer(),m_state,"TICK_UNAVAILABLE");
         SaveState();
         return;
        }
      ManagePendingEntry(tick);
      ManageOpenPositions(tick);
      ProcessM1(tick);
      ProcessM15(tick);
     }

   void OnTimer(void)
     {
      if(!m_initialized) return;
      if(m_state.state==FRANZ_STATE_EXIT_PENDING)
        {
         ulong positions[];
         if(OwnPositions(positions)==0)
           {
            if(GetTickCount64()-m_state.cleanup_started_ms>=250)
               FinalizeClosedSetup(TimeTradeServer());
            return;
           }
         const ulong elapsed=GetTickCount64()-m_state.cleanup_started_ms;
         if(m_state.cleanup_attempts>=20 || elapsed>=5000)
           {
            m_authority=false;
            m_state.state=FRANZ_STATE_FAILED;
            m_audit.Emit("ENGINE_ERROR",TimeTradeServer(),m_state,
               "CLOSE_RETRY_EXHAUSTED");
            SaveState();
            return;
           }
         m_state.cleanup_attempts++;
         for(int index=0;index<ArraySize(positions);index++) CloseTicket(positions[index]);
         SaveState();
        }
      if(m_state.tp1_hit && !m_state.leg2_closed &&
         m_state.cleanup_attempts>0 && m_state.cleanup_attempts<=20)
        {
         if(!ProtectSecondLeg() &&
            GetTickCount64()-m_state.cleanup_started_ms>=5000)
            CloseTicket(m_state.leg2_ticket);
        }
     }

   void OnTradeTransaction(const MqlTradeTransaction &transaction)
     {
      if(!m_initialized ||
         (m_state.state!=FRANZ_STATE_POSITION_OPEN &&
          m_state.state!=FRANZ_STATE_EXIT_PENDING) ||
         transaction.type!=TRADE_TRANSACTION_DEAL_ADD ||
         transaction.deal==0 || !HistoryDealSelect(transaction.deal) ||
         HistoryDealGetString(transaction.deal,DEAL_SYMBOL)!=FRANZ_SYMBOL ||
         HistoryDealGetInteger(transaction.deal,DEAL_MAGIC)!=FRANZ_MAGIC) return;
      const ENUM_DEAL_ENTRY entry=(ENUM_DEAL_ENTRY)HistoryDealGetInteger(
         transaction.deal,DEAL_ENTRY);
      if(entry!=DEAL_ENTRY_OUT && entry!=DEAL_ENTRY_OUT_BY) return;
      const ulong position_id=(ulong)HistoryDealGetInteger(
         transaction.deal,DEAL_POSITION_ID);
      const ENUM_DEAL_REASON deal_reason=(ENUM_DEAL_REASON)HistoryDealGetInteger(
         transaction.deal,DEAL_REASON);
      const double pnl=HistoryDealGetDouble(transaction.deal,DEAL_PROFIT)+
         HistoryDealGetDouble(transaction.deal,DEAL_SWAP)+
         HistoryDealGetDouble(transaction.deal,DEAL_COMMISSION)+
         HistoryDealGetDouble(transaction.deal,DEAL_FEE);
      m_state.setup_realized_pnl+=pnl;
      if(position_id==m_state.leg1_position_id)
        {
         m_state.leg1_closed=true;
         if(deal_reason==DEAL_REASON_TP && m_state.mode==FRANZ_MODE_SNIPER_TREND)
           {
            m_state.tp1_hit=true;
            m_state.cleanup_started_ms=GetTickCount64();
            m_state.cleanup_attempts=1;
            ProtectSecondLeg();
           }
         else if(m_state.mode==FRANZ_MODE_SNIPER_TREND && !m_state.leg2_closed)
            CloseTicket(m_state.leg2_ticket);
        }
      if(position_id==m_state.leg2_position_id) m_state.leg2_closed=true;
      SaveState();
      ulong positions[];
      if(OwnPositions(positions)==0)
        {
         m_state.state=FRANZ_STATE_EXIT_PENDING;
         m_state.close_reason="WAITING_FOR_CLOSE_DEALS";
         if(m_state.cleanup_started_ms==0) m_state.cleanup_started_ms=GetTickCount64();
         SaveState();
        }
     }

   void Deinitialize(const int reason)
     {
      EventKillTimer();
      if(m_rsi_m1!=INVALID_HANDLE) IndicatorRelease(m_rsi_m1);
      if(m_rsi_m5!=INVALID_HANDLE) IndicatorRelease(m_rsi_m5);
      if(m_stochastic_m1!=INVALID_HANDLE) IndicatorRelease(m_stochastic_m1);
      if(m_initialized) SaveState();
      m_initialized=false;
      m_authority=false;
      Print("FRANZ_STOP reason=",reason);
     }

   FranzPersistentState Snapshot(void) const { return m_state; }
  };

#endif
