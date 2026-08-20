#property strict
#property version "1.120"
#property description "Deterministic native Revised parity vector harness"

#include "../../Include/bot-ea/GoldEngineRevised.mqh"

bool HarnessPassed=false;

void SetHarnessBar(EngineBar &bar,
                   const ENUM_TIMEFRAMES timeframe,
                   const datetime open_time,
                   const double open,
                   const double high,
                   const double low,
                   const double close,
                   const int index)
  {
   bar.timeframe=timeframe;
   bar.open_time=open_time;
   bar.close_time=open_time+PeriodSeconds(timeframe);
   bar.open=open;
   bar.high=MathMax(high,MathMax(open,close));
   bar.low=MathMin(low,MathMin(open,close));
   bar.close=close;
   bar.tick_volume=100+index;
   bar.spread_points=20;
  }

void BuildRangeVector(CRevisedSnapshot &snapshot)
  {
   const datetime base=D'2026.08.18 12:00:00';
   ArrayResize(snapshot.m5_bars,20);
   for(int index=0;index<20;index++)
     {
      const double close=4392.0+(index%2==1 ? 0.2 : 0.0);
      SetHarnessBar(
         snapshot.m5_bars[index],PERIOD_M5,base+index*300,
         close-0.1,close+1.0,close-1.0,close,index);
     }

   const double values[][4]=
     {
      {4392.0,4393.0,4391.0,4392.5},
      {4392.0,4393.0,4391.0,4392.5},
      {4392.0,4393.0,4391.0,4392.5},
      {4392.0,4393.0,4391.0,4392.5},
      {4391.0,4394.0,4390.0,4393.5},
      {4393.5,4394.0,4392.0,4393.0},
      {4393.0,4394.0,4391.5,4392.5},
      {4392.5,4394.0,4390.0,4394.0},
      {4393.4,4394.0,4392.0,4393.2},
      {4393.2,4394.0,4391.5,4392.8},
      {4392.8,4394.0,4390.0,4394.0},
      {4393.4,4394.0,4392.0,4393.0},
      {4393.0,4394.0,4391.5,4392.7},
      {4392.7,4394.0,4390.0,4394.0},
      {4393.5,4394.0,4392.0,4393.0},
      {4393.0,4395.0,4392.5,4394.6}
     };
   ArrayResize(snapshot.m1_bars,16);
   for(int index=0;index<16;index++)
      SetHarnessBar(
         snapshot.m1_bars[index],PERIOD_M1,base+index*60,
         values[index][0],values[index][1],values[index][2],values[index][3],index);
   ArrayResize(snapshot.h1_bars,0);
   ArrayResize(snapshot.d1_bars,0);
   snapshot.symbol=_Symbol;
   snapshot.side=ENGINE_SIDE_BUY;
   snapshot.current_time=snapshot.m1_bars[15].open_time;
   snapshot.m5_trigger_time=snapshot.m1_bars[0].open_time-60;
   snapshot.m5_pattern="BULL_ENGULFING";
   snapshot.m5_votes=3;
   snapshot.confidence=92.0;
  }

bool CloseEnough(const double actual,const double expected,const double tolerance)
  {
   return MathAbs(actual-expected)<=tolerance;
  }

int OnInit(void)
  {
   CRevisedSnapshot snapshot;
   BuildRangeVector(snapshot);
   CRevisedEngine engine;
   engine.Initialize(_Symbol);
   RevisedDecision decision;
   string error="";
   const bool evaluated=engine.Evaluate(snapshot,decision,error);
   HarnessPassed=
      evaluated &&
      error=="OK" &&
      decision.state==REVISED_STATE_ENTRY_READY &&
      decision.action==REVISED_ACTION_ENTER &&
      decision.reason=="STRONG_FIRST_CONFIRMATION" &&
      decision.mode==REVISED_MODE_RANGE &&
      decision.entry_profile=="CORE" &&
      !decision.observation_only &&
      decision.touch_count==4 &&
      decision.rejection_count==4 &&
      decision.m1_votes==3 &&
      CloseEnough(decision.entry,4394.6,0.01) &&
      CloseEnough(decision.stop,4394.2,0.01) &&
      CloseEnough(decision.target,4399.76,0.01) &&
      CloseEnough(decision.first_obstacle,4400.0,0.01) &&
      decision.first_obstacle_kind=="PSYCH_10" &&
      CloseEnough(decision.confidence,80.0,1.0e-9);

   Print("G12_REVISED_PARITY profile=",_Symbol,
         " passed=",(HarnessPassed ? "true" : "false"),
         " error=",error,
         " state=",IntegerToString((long)decision.state),
         " reason=",decision.reason,
         " entry=",DoubleToString(decision.entry,2),
         " stop=",DoubleToString(decision.stop,2),
         " target=",DoubleToString(decision.target,2),
         " obstacle=",DoubleToString(decision.first_obstacle,2),
         " touches=",IntegerToString(decision.touch_count),
         " rejections=",IntegerToString(decision.rejection_count),
         " votes=",IntegerToString(decision.m1_votes));
   return HarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

void OnTick(void)
  {
   ExpertRemove();
  }

double OnTester(void)
  {
   return HarnessPassed ? 1.0 : 0.0;
  }
