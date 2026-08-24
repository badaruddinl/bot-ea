#property strict
#property version "1.000"

#include "../../Include/bot-ea/GoldIFranzPersistence.mqh"

void Require(const bool condition,const string label,bool &passed)
  {
   if(!condition) Print("FRANZ_HARNESS_CHECK_FAILED label=",label);
   passed=passed && condition;
  }

bool Near(const double left,const double right,const double tolerance=1e-7)
  {
   return MathAbs(left-right)<=tolerance;
  }

void BuildImpulseBars(FranzBar &bars[])
  {
   ArrayResize(bars,30);
   for(int index=0;index<30;index++)
     {
      bars[index].open_time=1000-index*900;
      bars[index].close_time=bars[index].open_time+900;
      bars[index].open=95.0;
      bars[index].close=95.2;
      bars[index].high=95.6;
      bars[index].low=94.6;
     }
   bars[2].open=100.0; bars[2].close=101.9; bars[2].high=102.0; bars[2].low=99.9;
   bars[1].open=102.1; bars[1].close=103.9; bars[1].high=104.0; bars[1].low=102.0;
   bars[0].open=104.1; bars[0].close=105.9; bars[0].high=106.0; bars[0].low=104.0;
   bars[3].close=99.8;
  }

void BuildTrendlineBars(FranzBar &bars[])
  {
   ArrayResize(bars,14);
   for(int index=0;index<14;index++)
     {
      bars[index].open_time=20000-index*60;
      bars[index].close_time=bars[index].open_time+60;
      bars[index].open=100.0;
      bars[index].close=100.1;
      bars[index].high=103.0;
      bars[index].low=97.0;
     }
   bars[3].low=95.0;
   bars[7].low=93.0;
   bars[4].high=108.0;
   bars[8].high=110.0;
  }

void BuildSupplyDemandBars(FranzBar &supply_bars[],FranzBar &demand_bars[])
  {
   ArrayResize(supply_bars,30);
   ArrayResize(demand_bars,30);
   for(int index=0;index<30;index++)
     {
      supply_bars[index].open_time=30000-index*900;
      supply_bars[index].close_time=supply_bars[index].open_time+900;
      supply_bars[index].open=100.0;
      supply_bars[index].close=100.1;
      supply_bars[index].high=100.5;
      supply_bars[index].low=99.5;
      demand_bars[index]=supply_bars[index];
     }
   supply_bars[6].open=110.0; supply_bars[6].close=110.1;
   supply_bars[6].high=110.5; supply_bars[6].low=109.7;
   supply_bars[7].open=110.0; supply_bars[7].close=109.9;
   supply_bars[7].high=110.4; supply_bars[7].low=109.6;
   supply_bars[5].open=109.5; supply_bars[5].close=108.8;
   supply_bars[5].high=109.6; supply_bars[5].low=108.7;
   supply_bars[4].open=108.7; supply_bars[4].close=108.0;
   supply_bars[4].high=108.8; supply_bars[4].low=107.9;
   supply_bars[3].open=107.9; supply_bars[3].close=107.4;
   supply_bars[3].high=108.0; supply_bars[3].low=107.3;

   demand_bars[6].open=90.0; demand_bars[6].close=89.9;
   demand_bars[6].high=90.3; demand_bars[6].low=89.5;
   demand_bars[7].open=90.0; demand_bars[7].close=90.1;
   demand_bars[7].high=90.4; demand_bars[7].low=89.6;
   demand_bars[5].open=90.5; demand_bars[5].close=91.2;
   demand_bars[5].high=91.3; demand_bars[5].low=90.4;
   demand_bars[4].open=91.3; demand_bars[4].close=92.0;
   demand_bars[4].high=92.1; demand_bars[4].low=91.2;
   demand_bars[3].open=92.1; demand_bars[3].close=92.6;
   demand_bars[3].high=92.7; demand_bars[3].low=92.0;
  }

int OnInit(void)
  {
   bool passed=true;

   FranzFibonacci sell_fib,buy_fib;
   Require(FranzComputeFibonacci(FRANZ_SIDE_SELL,100.0,110.0,sell_fib),
      "SELL_FIB_BUILD",passed);
   Require(Near(sell_fib.level_236,107.64),"SELL_FIB_236",passed);
   Require(Near(sell_fib.level_618,103.82),"SELL_FIB_618",passed);
   Require(Near(sell_fib.level_1130,111.30),"SELL_FIB_STOP",passed);
   Require(FranzComputeFibonacci(FRANZ_SIDE_BUY,110.0,100.0,buy_fib),
      "BUY_FIB_BUILD",passed);
   Require(Near(buy_fib.level_236,102.36),"BUY_FIB_236",passed);
   Require(Near(buy_fib.level_1130,98.70),"BUY_FIB_STOP",passed);

   Require(FranzSelectMode(1,1,1,FRANZ_SIDE_BUY,0.8)==FRANZ_MODE_SNIPER_TREND,
      "SNIPER_MODE",passed);
   Require(FranzSelectMode(1,-1,0,FRANZ_SIDE_SELL,0.30)==FRANZ_MODE_HANDGUN_RANGE,
      "HANDGUN_MODE",passed);
   Require(FranzSelectMode(1,-1,0,FRANZ_SIDE_SELL,0.60)==FRANZ_MODE_NONE,
      "NO_TRADE_MODE",passed);

   FranzBar impulse[];
   BuildImpulseBars(impulse);
   FranzSide impulse_side;
   double anchor=0.0,extreme=0.0,median=0.0;
   int impulse_count=0;
   bool terminal_wick=false;
   string reason="";
   Require(FranzEvaluateImpulse(impulse,impulse_side,anchor,extreme,median,
      impulse_count,terminal_wick,reason),"IMPULSE_BUILD",passed);
   Require(impulse_side==FRANZ_SIDE_SELL,"IMPULSE_SIDE",passed);
   Require(impulse_count>=3 && impulse_count<=8,"IMPULSE_COUNT",passed);

   FranzBar trendline_bars[];
   BuildTrendlineBars(trendline_bars);
   FranzTrendlineZone bull_zone,bear_zone;
   Require(FranzBuildTrendlineZone(trendline_bars,true,trendline_bars[0].close_time,
      6.0,0.20,bull_zone),"BULL_TRENDLINE_ZONE",passed);
   Require(FranzBuildTrendlineZone(trendline_bars,false,trendline_bars[0].close_time,
      6.0,0.20,bear_zone),"BEAR_TRENDLINE_ZONE",passed);
   Require(bull_zone.touches>=2 && bear_zone.touches>=2,
      "DUAL_TRENDLINE_TOUCHES",passed);
   FranzBar break_previous=trendline_bars[1];
   FranzBar break_current=trendline_bars[0];
   break_previous.close=FranzProjectTrendline(bull_zone,break_previous.close_time);
   break_current.open=FranzProjectTrendline(bull_zone,break_current.close_time);
   break_current.close=break_current.open-bull_zone.half_width-0.5;
   double break_level=0.0;
   Require(FranzInitialTrendlineBreak(FRANZ_SIDE_SELL,break_current,
      break_previous,bull_zone,bear_zone,break_level),"INITIAL_BULL_LINE_BREAK",passed);

   FranzBar supply_bars[],demand_bars[];
   BuildSupplyDemandBars(supply_bars,demand_bars);
   FranzSwingZone supply_zone,demand_zone;
   Require(FranzBuildSwingZone(supply_bars,6,true,1.0,supply_zone),
      "SUPPLY_ZONE",passed);
   Require(FranzBuildSwingZone(demand_bars,6,false,1.0,demand_zone),
      "DEMAND_ZONE",passed);
   Require(supply_zone.distal>supply_zone.proximal,"SUPPLY_BOUNDARIES",passed);
   Require(demand_zone.distal<demand_zone.proximal,"DEMAND_BOUNDARIES",passed);
   FranzBar deep_retest;
   ZeroMemory(deep_retest);
   deep_retest.open=100.6; deep_retest.close=101.1;
   deep_retest.high=101.2; deep_retest.low=100.5;
   Require(FranzFibRetest(FRANZ_SIDE_BUY,buy_fib,deep_retest),
      "DEEP_FIB_RETEST",passed);
   Require(FranzBarTouchesSwingZone(demand_zone,demand_bars[6],0.0),
      "DEMAND_ZONE_TOUCH",passed);

   Require(FranzStochasticReinforced(FRANZ_SIDE_SELL,
      76.0,81.0,86.0,82.0,90.0,84.0),"STOCH_SELL",passed);
   Require(FranzStochasticReinforced(FRANZ_SIDE_BUY,
      24.0,19.0,14.0,18.0,10.0,16.0),"STOCH_BUY",passed);
   Require(FranzRsiVotes(FRANZ_SIDE_SELL,110.0,111.0,78.0,72.0,
      58.0,62.0,66.0,52.0,60.0)==3,"RSI_SELL_VOTES",passed);
   Require(FranzRsiVotes(FRANZ_SIDE_BUY,100.0,99.0,22.0,28.0,
      42.0,38.0,34.0,48.0,40.0)==3,"RSI_BUY_VOTES",passed);

   FranzBar failed_break[];
   ArrayResize(failed_break,4);
   for(int index=0;index<4;index++)
     {
      failed_break[index].open=110.0;
      failed_break[index].high=110.2;
      failed_break[index].low=109.2;
      failed_break[index].close=109.8;
     }
   failed_break[0].close=109.3;
   int reentries=0;
   bool micro=false,accepted=false;
   Require(FranzFailedBreakConfirmed(failed_break,FRANZ_SIDE_SELL,110.0,
      110.3,109.5,false,reentries,micro,accepted,reason),
      "FAILED_BREAK_TWO_REENTRY",passed);
   failed_break[1].close=110.1;
   Require(FranzFailedBreakConfirmed(failed_break,FRANZ_SIDE_SELL,110.0,
      110.3,109.5,true,reentries,micro,accepted,reason),
      "FAILED_BREAK_STOCH_REINFORCED",passed);

   CFranzStateStore store;
   store.Configure("harness");
   store.DeleteTestState();
   FranzPersistentState state;
   FranzResetPersistentState(state);
   state.state=FRANZ_STATE_FIB_RECLAIMED;
   state.mode=FRANZ_MODE_SNIPER_TREND;
   state.side=FRANZ_SIDE_BUY;
   state.day_key=2026236;
   state.setup_id="FRZ-TEST";
   state.fibonacci=buy_fib;
   state.bull_zone=bull_zone;
   state.bear_zone=bear_zone;
   state.supply_zone=supply_zone;
   state.demand_zone=demand_zone;
   state.initial_trendline_break=true;
   state.initial_break_level=99.0;
   state.shakeout_evidence_locked=true;
   state.stop_loss=98.70;
   state.take_profit_1=106.18;
   state.take_profit_2=110.0;
   state.close_reason="HARNESS";
   Require(store.Save(state),"PERSIST_SAVE",passed);
   FranzPersistentState restored;
   Require(store.Load(restored)==FRANZ_LOAD_VALID,"PERSIST_LOAD",passed);
   Require(restored.state==FRANZ_STATE_FIB_RECLAIMED,"PERSIST_STATE",passed);
   Require(restored.fibonacci.locked,"PERSIST_FIB_LOCK",passed);
   Require(restored.bull_zone.valid && restored.bear_zone.valid,
      "PERSIST_TRENDLINES",passed);
   Require(restored.supply_zone.valid && restored.demand_zone.valid,
      "PERSIST_SWING_ZONES",passed);
   Require(restored.shakeout_evidence_locked,"PERSIST_SHAKEOUT_LOCK",passed);
   Require(restored.setup_id=="FRZ-TEST","PERSIST_SETUP",passed);
   store.DeleteTestState();

   Print("FRANZ_HARNESS passed=",passed ? "true" : "false",
         " authority=DISABLED orders_sent=0");
   return passed ? INIT_SUCCEEDED : INIT_FAILED;
  }

void OnTick(void) {}
