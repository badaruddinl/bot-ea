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
   snapshot.has_entry=false;
   snapshot.has_stop=false;
   snapshot.has_level=false;
   snapshot.has_invalidation=false;
  }

void BuildSellRangeVector(CRevisedSnapshot &snapshot)
  {
   BuildRangeVector(snapshot);
   const datetime base=D'2026.08.18 12:00:00';
   const double values[][4]=
     {
      {4402.0,4404.0,4401.0,4402.5},
      {4402.0,4404.0,4401.0,4402.5},
      {4402.0,4404.0,4401.0,4402.5},
      {4402.0,4404.0,4401.0,4402.5},
      {4404.0,4405.0,4401.0,4401.5},
      {4401.5,4403.0,4400.5,4401.8},
      {4401.8,4403.5,4400.8,4402.0},
      {4402.0,4405.0,4401.0,4401.6},
      {4401.6,4403.0,4400.5,4401.9},
      {4401.9,4403.5,4400.8,4402.1},
      {4402.1,4405.0,4401.0,4401.7},
      {4401.7,4403.0,4400.5,4401.9},
      {4401.9,4403.5,4400.8,4402.0},
      {4402.0,4405.0,4401.0,4401.8},
      {4401.8,4403.0,4400.5,4401.7},
      {4401.7,4402.0,4398.5,4399.0}
     };
   for(int index=0;index<16;index++)
      SetHarnessBar(
         snapshot.m1_bars[index],PERIOD_M1,base+index*60,
         values[index][0],values[index][1],values[index][2],values[index][3],index);
   snapshot.side=ENGINE_SIDE_SELL;
   snapshot.current_time=snapshot.m1_bars[15].open_time;
   snapshot.m5_pattern="BEAR_ENGULFING";
  }

bool CloseEnough(const double actual,const double expected,const double tolerance)
  {
   return MathAbs(actual-expected)<=tolerance;
  }

bool EvaluateRangeCase(CRevisedEngine &engine)
  {
   CRevisedSnapshot snapshot;
   BuildRangeVector(snapshot);
   RevisedDecision decision;
   string error="";
   return engine.Evaluate(snapshot,decision,error) &&
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
  }

bool EvaluateNoSetupCase(CRevisedEngine &engine)
  {
   CRevisedSnapshot snapshot;
   BuildRangeVector(snapshot);
   snapshot.m5_trigger_time=0;
   snapshot.m5_pattern="NONE";
   RevisedDecision decision;
   string error="";
   return engine.Evaluate(snapshot,decision,error) &&
          error=="OK" &&
          decision.state==REVISED_STATE_WAIT &&
          decision.action==REVISED_ACTION_OBSERVE &&
          decision.reason=="M5_SETUP_UNAVAILABLE" &&
          CloseEnough(decision.confidence,59.99,1.0e-9);
  }

bool EvaluateSellRangeCase(CRevisedEngine &engine)
  {
   CRevisedSnapshot snapshot;
   BuildSellRangeVector(snapshot);
   RevisedDecision decision;
   string error="";
   return engine.Evaluate(snapshot,decision,error) &&
          error=="OK" &&
          decision.state==REVISED_STATE_ENTRY_READY &&
          decision.action==REVISED_ACTION_ENTER &&
          decision.reason=="STRONG_FIRST_CONFIRMATION" &&
          decision.mode==REVISED_MODE_RANGE &&
          decision.observation_only &&
          decision.entry_profile=="CORE" &&
          decision.touch_count==4 &&
          decision.rejection_count==4 &&
          decision.m1_votes==3 &&
          CloseEnough(decision.entry,4399.0,0.01) &&
          CloseEnough(decision.stop,4399.4,0.01) &&
          CloseEnough(decision.target,4390.24,0.01) &&
          CloseEnough(decision.first_obstacle,4390.0,0.01) &&
          decision.first_obstacle_kind=="PSYCH_10";
  }

bool EvaluateObstacleCase(CRevisedEngine &engine)
  {
   CRevisedSnapshot snapshot;
   BuildRangeVector(snapshot);
   snapshot.has_entry=true;
   snapshot.entry=4399.7;
   snapshot.has_stop=true;
   snapshot.stop=4398.7;
   RevisedDecision decision;
   string error="";
   return engine.Evaluate(snapshot,decision,error) &&
          error=="OK" &&
          decision.state==REVISED_STATE_WATCH &&
          decision.action==REVISED_ACTION_OBSERVE &&
          decision.reason=="SOFT_FAIL_FIRST_OBSTACLE_ROOM" &&
          decision.first_obstacle_kind=="PSYCH_10" &&
          CloseEnough(decision.first_obstacle,4400.0,0.01) &&
          CloseEnough(decision.first_obstacle_r,0.3,1.0e-9);
  }

bool EvaluateMomentumCase(CRevisedEngine &engine)
  {
   CRevisedSnapshot snapshot;
   BuildRangeVector(snapshot);
   const datetime base=D'2026.08.18 12:00:00';
   for(int index=0;index<20;index++)
     {
      const double open=4390.0+index*2.0;
      const double close=4392.0+index*2.0;
      SetHarnessBar(
         snapshot.m5_bars[index],PERIOD_M5,base+index*300,
         open,close,4389.0+index*2.0,close,index);
     }
   snapshot.has_entry=true;
   snapshot.entry=4394.0;
   snapshot.has_stop=true;
   snapshot.stop=4390.0;
   RevisedDecision decision;
   string error="";
   return engine.Evaluate(snapshot,decision,error) &&
          error=="OK" &&
          decision.state==REVISED_STATE_ENTRY_READY &&
          decision.action==REVISED_ACTION_ENTER &&
          decision.reason=="MOMENTUM_ENTRY" &&
          decision.mode==REVISED_MODE_MOMENTUM &&
          CloseEnough(decision.entry,4394.0,0.01) &&
          CloseEnough(decision.stop,4390.0,0.01) &&
          CloseEnough(decision.target,4399.64,0.01) &&
          CloseEnough(decision.first_obstacle_r,1.5,1.0e-9);
  }

int OnInit(void)
  {
   CRevisedEngine engine;
   engine.Initialize(_Symbol);
   const bool range_passed=EvaluateRangeCase(engine);
   const bool sell_range_passed=EvaluateSellRangeCase(engine);
   const bool no_setup_passed=EvaluateNoSetupCase(engine);
   const bool obstacle_passed=EvaluateObstacleCase(engine);
   const bool momentum_passed=EvaluateMomentumCase(engine);
   HarnessPassed=range_passed &&
                 sell_range_passed &&
                 no_setup_passed &&
                 obstacle_passed &&
                 momentum_passed;
   Print("G12_REVISED_PARITY profile=",_Symbol,
         " passed=",(HarnessPassed ? "true" : "false"),
         " range=",(range_passed ? "true" : "false"),
         " sell_range=",(sell_range_passed ? "true" : "false"),
         " no_setup=",(no_setup_passed ? "true" : "false"),
         " obstacle=",(obstacle_passed ? "true" : "false"),
         " momentum=",(momentum_passed ? "true" : "false"));
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
