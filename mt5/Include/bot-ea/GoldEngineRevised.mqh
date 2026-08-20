#ifndef GOLD_ENGINE_REVISED_MQH
#define GOLD_ENGINE_REVISED_MQH

#include "GoldEngineRevisedGeometry.mqh"
#include "GoldEngineRevisedSetup.mqh"

bool RevisedStrongM5Pattern(const RevisedEngineConfig &config,const string pattern)
  {
   for(int index=0;index<6;index++)
     {
      if(config.strong_m5_patterns[index]==pattern)
         return true;
     }
   return false;
  }

void InitializeRevisedDecision(const CRevisedSnapshot &snapshot,
                               const RevisedState state,
                               const RevisedAction action,
                               const string reason,
                               const double confidence,
                               RevisedDecision &decision)
  {
   decision.strategy_id="GOLDM_REVISED";
   decision.strategy_version="0.6.0";
   decision.symbol=snapshot.symbol;
   decision.side=snapshot.side;
   decision.state=state;
   decision.action=action;
   decision.entry_profile="CORE";
   decision.observation_only=(snapshot.side==ENGINE_SIDE_SELL);
   decision.setup_trigger_time=snapshot.m5_trigger_time;
   decision.time=snapshot.current_time;
   decision.reason=reason;
   decision.validation_status="WATCH_ONLY";
   decision.retest_count=0;
   decision.confidence=confidence;
   decision.mode=REVISED_MODE_NONE;
   decision.exhausted=false;
   decision.has_entry=false;
   decision.entry=0.0;
   decision.has_stop=false;
   decision.stop=0.0;
   decision.has_target=false;
   decision.target=0.0;
   decision.has_first_obstacle=false;
   decision.first_obstacle=0.0;
   decision.first_obstacle_kind="";
   decision.has_first_obstacle_r=false;
   decision.first_obstacle_r=0.0;
   decision.touch_count=0;
   decision.rejection_count=0;
   decision.acceptance_count=0;
   decision.m1_votes=0;
  }

void SetRevisedDecisionEvidence(const RevisedRangeStats &range_stats,
                                const RevisedM1Confirmation &m1,
                                const RevisedFibonacciStats &fibonacci,
                                const bool exhausted,
                                const double entry,
                                const double stop,
                                const bool has_obstacle,
                                const double obstacle,
                                const string obstacle_kind,
                                const bool has_obstacle_r,
                                const double obstacle_r,
                                RevisedDecision &decision)
  {
   decision.retest_count=fibonacci.retests;
   decision.exhausted=exhausted;
   decision.has_entry=true;
   decision.entry=entry;
   decision.has_stop=true;
   decision.stop=stop;
   decision.has_first_obstacle=has_obstacle;
   decision.first_obstacle=obstacle;
   decision.first_obstacle_kind=(has_obstacle ? obstacle_kind : "");
   decision.has_first_obstacle_r=has_obstacle_r;
   decision.first_obstacle_r=(has_obstacle_r ? obstacle_r : 0.0);
   decision.touch_count=range_stats.touches;
   decision.rejection_count=range_stats.rejections;
   decision.acceptance_count=range_stats.acceptance;
   decision.m1_votes=m1.votes;
  }

class CRevisedEngine
  {
private:
   RevisedEngineConfig m_config;

public:
   CRevisedEngine(void)
     {
      LoadRevisedConfig(m_config,"GOLD.i#");
     }

   void Initialize(const string symbol)
     {
      LoadRevisedConfig(m_config,symbol);
     }

   void TerminalDecision(const CRevisedSnapshot &snapshot,
                         const string reason,
                         RevisedDecision &decision)
     {
      InitializeRevisedDecision(
         snapshot,REVISED_STATE_CANCELLED,REVISED_ACTION_CANCEL,reason,
         MathMin(snapshot.confidence,m_config.promotion_confidence-0.01),
         decision);
      decision.validation_status="HARD_INVALID";
     }

   bool Evaluate(const CRevisedSnapshot &snapshot,
                 RevisedDecision &decision,
                 string &error)
     {
      if(!ValidateRevisedSnapshot(snapshot,error))
         return false;
      if(snapshot.symbol!=m_config.symbol)
        {
         error="REVISED_PROFILE_SYMBOL_MISMATCH";
         return false;
        }
      if(snapshot.m5_trigger_time<=0 || snapshot.m5_pattern=="NONE")
        {
         InitializeRevisedDecision(
            snapshot,REVISED_STATE_WAIT,REVISED_ACTION_OBSERVE,
            "M5_SETUP_UNAVAILABLE",
            MathMin(snapshot.confidence,m_config.promotion_confidence-0.01),
            decision);
         error="OK";
         return true;
        }

      const EngineSide side=snapshot.side;
      const int m1_count=ArraySize(snapshot.m1_bars);
      const double atr_m1=RevisedAtr(snapshot.m1_bars,m_config.atr_period);
      const double atr_m5=RevisedAtr(snapshot.m5_bars,m_config.atr_period);
      const double entry=(snapshot.has_entry ?
                          snapshot.entry :
                          snapshot.m1_bars[m1_count-1].close);
      if(atr_m1<=0.0 || atr_m5<=0.0)
        {
         InitializeRevisedDecision(
            snapshot,REVISED_STATE_WAIT,REVISED_ACTION_OBSERVE,
            "ATR_UNAVAILABLE",snapshot.confidence,decision);
         error="OK";
         return true;
        }

      RevisedRiskStats risk_stats;
      const double stop=RevisedEntryStop(
         snapshot,m_config,entry,atr_m1,atr_m5,risk_stats);
      const double risk=MathAbs(entry-stop);
      RevisedFibonacciStats fibonacci;
      RevisedFibonacciStatistics(snapshot,m_config,side,atr_m1,fibonacci);
      const bool hard_invalidation=RevisedHardInvalidation(
         snapshot,m_config,side,atr_m1);
      double obstacle=0.0;
      string obstacle_kind="";
      const bool has_obstacle=RevisedFirstObstacle(
         snapshot,m_config,entry,atr_m1,obstacle,obstacle_kind);
      const bool has_obstacle_r=has_obstacle && risk>0.0;
      const double obstacle_r=(has_obstacle_r ?
                               MathAbs(obstacle-entry)/risk : 0.0);
      RevisedRangeStats range_stats;
      RevisedRangeStatistics(snapshot,m_config,side,atr_m1,range_stats);
      RevisedMomentumStats momentum_stats;
      RevisedMomentumStatistics(snapshot,m_config,side,atr_m5,momentum_stats);
      RevisedM1Confirmation m1;
      RevisedM1ConfirmationLatest(snapshot.m1_bars,side,m1);
      const bool strong_m1_now=RevisedStrongM1Confirmation(m1,m_config);
      const bool strong_m1_latched=RevisedStrongM1Latched(
         snapshot,m_config,side);
      const bool fibonacci_ok=
         fibonacci.retests>=1 &&
         fibonacci.current_rejection &&
         m1.votes==3 &&
         m1.micro_break;
      const bool range_ok=
         RevisedRangeConfirmed(range_stats,m1,m_config) || fibonacci_ok;
      const bool strict_room=
         has_obstacle_r && obstacle_r<m_config.first_obstacle_strict_r;
      const bool momentum_ok=
         momentum_stats.momentum &&
         !momentum_stats.exhausted &&
         has_obstacle_r &&
         obstacle_r>=m_config.first_obstacle_strict_r &&
         snapshot.m5_votes>=m_config.minimum_m5_votes;
      const bool strong_pattern=RevisedStrongM5Pattern(
         m_config,snapshot.m5_pattern);

      RevisedZone supply_context;
      const bool has_supply=RevisedNearestSupplyZone(
         snapshot,entry,false,m_config,supply_context);
      const bool inside_h1_supply=
         has_supply && supply_context.kind=="H1_SUPPLY_INSIDE";
      RevisedMarketRegimeStats regime;
      RevisedMarketRegime(snapshot,m_config,regime);
      const bool h1_supply_breakout_ok=
         inside_h1_supply &&
         regime.above_h1_sma20 &&
         m_config.h1_supply_breakout_trend_min_atr<=regime.h1_trend_atr &&
         regime.h1_trend_atr<m_config.h1_supply_breakout_trend_max_atr &&
         regime.h1_efficiency<m_config.h1_supply_breakout_max_efficiency;
      const bool supply_entry_context_ok=!has_supply || h1_supply_breakout_ok;
      const bool strong_first_ok=
         has_obstacle_r &&
         obstacle_r>=m_config.first_obstacle_strict_r &&
         strong_pattern &&
         snapshot.m5_votes>=m_config.minimum_m5_votes &&
         strong_m1_now &&
         range_stats.acceptance==0;
      const bool latched_retest_ok=
         has_obstacle_r &&
         obstacle_r>=m_config.first_obstacle_strict_r &&
         strong_pattern &&
         snapshot.m5_votes>=m_config.minimum_m5_votes &&
         strong_m1_latched &&
         fibonacci.retests>=1 &&
         m1.directional &&
         !inside_h1_supply &&
         range_stats.acceptance==0;
      const bool strict_ok=
         has_obstacle_r &&
         obstacle_r>=m_config.first_obstacle_reject_r &&
         m1.votes==3 &&
         m1.micro_break &&
         strong_pattern &&
         snapshot.m5_votes>=m_config.minimum_m5_votes &&
         range_ok;
      const bool scalper_ok=
         side==ENGINE_SIDE_BUY &&
         has_obstacle_r &&
         m_config.scalper_min_obstacle_r<=obstacle_r &&
         obstacle_r<m_config.first_obstacle_reject_r &&
         StringFind(obstacle_kind,"PSYCH_")!=0 &&
         !has_supply &&
         strong_pattern &&
         m1.votes==3 &&
         m1.micro_break &&
         fibonacci.retests>=1 &&
         (fibonacci.current_rejection ||
          RevisedRangeConfirmed(range_stats,m1,m_config)) &&
         range_stats.acceptance==0;

      if(hard_invalidation)
        {
         InitializeRevisedDecision(
            snapshot,REVISED_STATE_CANCELLED,REVISED_ACTION_CANCEL,
            "HARD_INVALIDATION_ACCEPTED",
            MathMin(snapshot.confidence,m_config.promotion_confidence-0.01),
            decision);
         decision.validation_status="HARD_INVALID";
         SetRevisedDecisionEvidence(
            range_stats,m1,fibonacci,momentum_stats.exhausted,
            entry,stop,has_obstacle,obstacle,obstacle_kind,
            has_obstacle_r,obstacle_r,decision);
         error="OK";
         return true;
        }
      if(!has_obstacle_r ||
         obstacle_r<m_config.first_obstacle_reject_r)
        {
         if(scalper_ok)
           {
            double target=0.0;
            const bool has_target=RevisedTarget(
               m_config,side,entry,has_obstacle,obstacle,atr_m5,true,target);
            if(has_target && target>entry)
              {
               InitializeRevisedDecision(
                  snapshot,REVISED_STATE_ENTRY_READY,REVISED_ACTION_ENTER,
                  "SCALPER_FIRST_OBSTACLE_ENTRY",
                  MathMin(snapshot.confidence,m_config.promotion_confidence-0.01),
                  decision);
               decision.mode=REVISED_MODE_RANGE;
               decision.observation_only=true;
               decision.entry_profile="SCALPER";
               decision.validation_status="VALID";
               decision.has_target=true;
               decision.target=target;
               SetRevisedDecisionEvidence(
                  range_stats,m1,fibonacci,momentum_stats.exhausted,
                  entry,stop,has_obstacle,obstacle,obstacle_kind,
                  has_obstacle_r,obstacle_r,decision);
               error="OK";
               return true;
              }
           }
         InitializeRevisedDecision(
            snapshot,REVISED_STATE_WATCH,REVISED_ACTION_OBSERVE,
            "SOFT_FAIL_FIRST_OBSTACLE_ROOM",
            MathMin(snapshot.confidence,m_config.promotion_confidence-0.01),
            decision);
         decision.validation_status=(fibonacci.retests>0 ?
                                     "SOFT_FAIL" : "WATCH_ONLY");
         SetRevisedDecisionEvidence(
            range_stats,m1,fibonacci,momentum_stats.exhausted,
            entry,stop,has_obstacle,obstacle,obstacle_kind,
            has_obstacle_r,obstacle_r,decision);
         error="OK";
         return true;
        }

      RevisedConfirmationMode mode=REVISED_MODE_NONE;
      if(momentum_stats.exhausted)
         mode=REVISED_MODE_RANGE;
      else if(momentum_ok)
         mode=REVISED_MODE_MOMENTUM;
      else if(strong_first_ok || latched_retest_ok || range_ok)
         mode=REVISED_MODE_RANGE;
      else
         mode=(strict_room ? REVISED_MODE_RANGE : REVISED_MODE_NONE);
      const bool eligible=
         supply_entry_context_ok &&
         (momentum_ok ||
          strong_first_ok ||
          latched_retest_ok ||
          (range_ok && (!strict_room || strict_ok)));
      if(!eligible)
        {
         InitializeRevisedDecision(
            snapshot,REVISED_STATE_WATCH,REVISED_ACTION_OBSERVE,
            !supply_entry_context_ok ?
            "SUPPLY_CONTEXT_PENDING" :
            "M1_RANGE_OR_MOMENTUM_GATE_PENDING",
            MathMin(snapshot.confidence,m_config.promotion_confidence-0.01),
            decision);
         decision.mode=mode;
         decision.validation_status=(fibonacci.retests>0 ?
                                     "SOFT_FAIL" : "WATCH_ONLY");
         SetRevisedDecisionEvidence(
            range_stats,m1,fibonacci,momentum_stats.exhausted,
            entry,stop,has_obstacle,obstacle,obstacle_kind,
            has_obstacle_r,obstacle_r,decision);
         error="OK";
         return true;
        }

      double target=0.0;
      const bool has_target=RevisedTarget(
         m_config,side,entry,has_obstacle,obstacle,atr_m5,false,target);
      const int retest_count=fibonacci.retests;
      const bool local_retest_scalper=
         side==ENGINE_SIDE_BUY &&
         obstacle_kind=="M5_SWING" &&
         has_obstacle_r &&
         obstacle_r<2.0 &&
         retest_count>=2;
      double confidence=MathMin(100.0,MathMax(0.0,snapshot.confidence));
      confidence=MathMin(confidence,m_config.promotion_confidence+20.0);
      if(strict_room && !strict_ok)
         confidence=MathMin(confidence,m_config.promotion_confidence-0.01);
      const string reason=(mode==REVISED_MODE_MOMENTUM ?
                           "MOMENTUM_ENTRY" :
                           strong_first_ok ?
                           "STRONG_FIRST_CONFIRMATION" :
                           latched_retest_ok ?
                           "LATCHED_CONFIRMATION_RETEST" :
                           "RANGE_REJECTIONS_CONFIRMED");
      InitializeRevisedDecision(
         snapshot,REVISED_STATE_ENTRY_READY,REVISED_ACTION_ENTER,
         reason,confidence,decision);
      decision.mode=mode;
      decision.observation_only=
         side==ENGINE_SIDE_SELL || local_retest_scalper;
      decision.entry_profile=(local_retest_scalper ? "SCALPER" : "CORE");
      decision.validation_status="VALID";
      decision.has_target=has_target;
      decision.target=(has_target ? target : 0.0);
      SetRevisedDecisionEvidence(
         range_stats,m1,fibonacci,momentum_stats.exhausted,
         entry,stop,has_obstacle,obstacle,obstacle_kind,
         has_obstacle_r,obstacle_r,decision);
      error="OK";
      return true;
     }
  };

#endif
