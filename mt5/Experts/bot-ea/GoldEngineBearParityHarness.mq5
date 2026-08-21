#property strict
#property version "1.130"
#property description "Deterministic native incremental Bear parity harness"

#include "../../Include/bot-ea/GoldEngineBearValidation.mqh"

bool BearHarnessPassed=false;

void SetBearHarnessBar(EngineBar &bar,
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

void BuildBearH1(EngineBar &bars[])
  {
   const datetime available=D'2026.01.02 00:15:00';
   ArrayResize(bars,22);
   for(int index=0;index<22;index++)
     {
      const double open=120.0-index;
      SetBearHarnessBar(
         bars[index],PERIOD_H1,
         available-(22-index)*3600,
         open,120.2-index,118.8-index,119.0-index,index);
     }
  }

void BuildBearM5(EngineBar &history[],EngineBar &candidates[])
  {
   const datetime available=D'2026.01.02 00:15:00';
   EngineBar all[];
   ArrayResize(all,22);
   for(int index=0;index<20;index++)
      SetBearHarnessBar(
         all[index],PERIOD_M5,
         available-(20-index)*300,
         99.2,99.7,98.7,99.1,index);
   SetBearHarnessBar(
      all[20],PERIOD_M5,available,
      99.5,100.1,99.0,99.8,20);
   SetBearHarnessBar(
      all[21],PERIOD_M5,available+300,
      100.0,100.2,97.8,98.1,21);
   ArrayResize(history,17);
   for(int index=0;index<17;index++)
      history[index]=all[index];
   ArrayResize(candidates,5);
   for(int index=0;index<5;index++)
      candidates[index]=all[17+index];
  }

void BuildBearM1(EngineBar &history[],EngineBar &candidates[])
  {
   const datetime armed=D'2026.01.02 00:25:00';
   ArrayResize(history,20);
   for(int index=0;index<20;index++)
      SetBearHarnessBar(
         history[index],PERIOD_M1,
         armed-(20-index)*60,
         98.7,99.0,98.2,98.6,index);
   ArrayResize(candidates,3);
   SetBearHarnessBar(
      candidates[0],PERIOD_M1,armed,
      99.0,99.5,97.8,98.0,20);
   SetBearHarnessBar(
      candidates[1],PERIOD_M1,armed+60,
      98.0,98.5,97.7,97.9,21);
   SetBearHarnessBar(
      candidates[2],PERIOD_M1,armed+120,
      99.2,99.4,96.9,97.1,22);
  }

BearSetup BearFixtureSetup(void)
  {
   BearSetup setup;
   setup.time=D'2026.01.02 00:00:00';
   setup.symbol=_Symbol;
   setup.reason="v4_incremental_fixture";
   setup.score=90;
   setup.resistance=100.0;
   setup.entry=99.0;
   setup.stop=101.0;
   setup.take_profit=94.0;
   setup.reward_risk=2.5;
   return setup;
  }

bool BearCloseEnough(const double actual,
                     const double expected,
                     const double tolerance)
  {
   return MathAbs(actual-expected)<=tolerance;
  }

bool EvaluateBearHappyPath(void)
  {
   const bool goldm=_Symbol=="GOLDm#";
   BearV4Config config;
   LoadBearV4Config(config,goldm ? 0.24 : 0.20);
   EngineBar h1[];
   BuildBearH1(h1);
   if(!BearH1Bearish(h1,config.h1_sma_period))
      return false;
   EngineBar m5_history[];
   EngineBar m5_candidates[];
   BuildBearM5(m5_history,m5_candidates);
   const BearSetup setup=BearFixtureSetup();
   const BearM5Result arm=BearArmOnM5(
      setup,m5_history,m5_candidates,
      D'2026.01.02 00:15:00',config);
   if(arm.state!=BEAR_M5_ARMED ||
      arm.armed_at!=D'2026.01.02 00:25:00' ||
      arm.touches!=2 ||
      arm.rejections!=2 ||
      !BearCloseEnough(arm.atr,1.1071428571428572,1.0e-12) ||
      !BearCloseEnough(arm.recent_high,100.2,1.0e-12))
      return false;
   EngineBar m1_history[];
   EngineBar m1_candidates[];
   BuildBearM1(m1_history,m1_candidates);
   BearEntryPlan plan;
   if(!BearEntryOnM1(
         setup,arm,m1_history,m1_candidates,config,plan))
      return false;
   const double expected_stop=(goldm ? 100.68 : 100.60);
   const double expected_target=(goldm ? 93.21 : 93.37);
   return plan.valid &&
          plan.opened_at==D'2026.01.02 00:26:00' &&
          plan.m5_touches==2 &&
          plan.m5_rejections==2 &&
          plan.m1_touches==1 &&
          BearCloseEnough(plan.entry,98.19,0.01) &&
          BearCloseEnough(plan.stop,expected_stop,0.01) &&
          BearCloseEnough(plan.structural_stop,expected_stop,0.01) &&
          BearCloseEnough(plan.target,expected_target,0.01) &&
          BearCloseEnough(plan.structural_target,94.0,0.01);
  }

int OnInit(void)
  {
   BearHarnessPassed=EvaluateBearHappyPath();
   Print("G13_BEAR_PARITY profile=",_Symbol,
         " passed=",(BearHarnessPassed ? "true" : "false"),
         " h1_m5_m1=",(BearHarnessPassed ? "true" : "false"));
   return BearHarnessPassed ? INIT_SUCCEEDED : INIT_FAILED;
  }

void OnTick(void)
  {
   ExpertRemove();
  }

double OnTester(void)
  {
   return BearHarnessPassed ? 1.0 : 0.0;
  }
