#ifndef GOLD_ENGINE_RUNTIME_MQH
#define GOLD_ENGINE_RUNTIME_MQH

#include "GoldEngineProfile.mqh"
#include "GoldEngineRevisedGeometry.mqh"
#include "GoldEngineRevised.mqh"
#include "GoldEngineRevisedSetup.mqh"
#include "GoldEngineScheduler.mqh"

class CGoldEngineRuntime
  {
private:
   ProfileConfig       m_profile;
   StrategyState       m_state;
   CClosedBarScheduler m_scheduler;
   EngineEvent         m_last_event;
   CRevisedEngine      m_revised_engine;
   CRevisedSetupDetector m_revised_detector;
   RevisedDecision     m_last_revised_decision;
   bool                m_has_revised_decision;
   EngineBar           m_d1_history[];
   EngineBar           m_h1_history[];
   EngineBar           m_m15_history[];
   EngineBar           m_m5_history[];
   EngineBar           m_m1_history[];
   bool                m_initialized;
   bool                m_data_healthy;

   void SetEvent(const EngineEventType type,const datetime server_time,const string reason)
     {
      m_last_event.type=type;
      m_last_event.profile_id=m_profile.profile_id;
      m_last_event.server_time=server_time;
      m_last_event.reason=reason;
      m_last_event.event_id=
         m_profile.profile_id+"-"+IntegerToString((long)type)+"-"+
         IntegerToString((long)server_time);
     }

   bool LoadHistory(const ENUM_TIMEFRAMES timeframe,
                    const int required_bars,
                    EngineBar &history[])
     {
      if(required_bars<=0 || required_bars>512)
         return false;
      MqlRates rates[];
      ArraySetAsSeries(rates,true);
      if(CopyRates(m_profile.symbol,timeframe,1,required_bars,rates)!=required_bars)
         return false;
      ArrayResize(history,required_bars);
      const int seconds=PeriodSeconds(timeframe);
      for(int index=0;index<required_bars;index++)
        {
         const MqlRates rate=rates[required_bars-index-1];
         history[index].timeframe=timeframe;
         history[index].open_time=rate.time;
         history[index].close_time=rate.time+seconds;
         history[index].open=rate.open;
         history[index].high=rate.high;
         history[index].low=rate.low;
         history[index].close=rate.close;
         history[index].tick_volume=rate.tick_volume;
         history[index].spread_points=rate.spread;
        }
      return true;
     }

   bool Warmup(void)
     {
      if(!LoadHistory(PERIOD_D1,30,m_d1_history))
         return false;
      if(!LoadHistory(PERIOD_H1,200,m_h1_history))
         return false;
      if(!LoadHistory(PERIOD_M15,300,m_m15_history))
         return false;
      if(!LoadHistory(PERIOD_M5,300,m_m5_history))
         return false;
      if(!LoadHistory(PERIOD_M1,300,m_m1_history))
         return false;
      m_state.warmed=true;
      return true;
     }

   void AppendBounded(EngineBar &history[],
                      const EngineBar &bar,
                      const int maximum)
     {
      const int count=ArraySize(history);
      if(count>0 && bar.open_time<=history[count-1].open_time)
         return;
      if(count<maximum)
        {
         ArrayResize(history,count+1);
         history[count]=bar;
         return;
        }
      for(int index=1;index<count;index++)
         history[index-1]=history[index];
      history[count-1]=bar;
     }

   void BuildRevisedSnapshot(const EngineSide side,
                             const RevisedM5Setup &setup,
                             CRevisedSnapshot &snapshot)
     {
      snapshot.symbol=m_profile.symbol;
      snapshot.side=side;
      const int m1_count=ArraySize(m_m1_history);
      snapshot.current_time=(m1_count>0 ?
                             m_m1_history[m1_count-1].open_time :
                             TimeCurrent());
      ArrayCopy(snapshot.m1_bars,m_m1_history);
      ArrayCopy(snapshot.m5_bars,m_m5_history);
      ArrayCopy(snapshot.h1_bars,m_h1_history);
      ArrayCopy(snapshot.d1_bars,m_d1_history);
      snapshot.m5_trigger_time=setup.trigger_time;
      snapshot.m5_pattern=setup.pattern;
      snapshot.m5_votes=setup.votes;
      snapshot.confidence=setup.confidence;
      snapshot.level=setup.level;
      snapshot.has_level=true;
      snapshot.invalidation=setup.invalidation;
      snapshot.has_invalidation=true;
      snapshot.entry=0.0;
      snapshot.has_entry=false;
      snapshot.stop=0.0;
      snapshot.has_stop=false;
     }

   void EvaluateRevisedSide(const EngineSide side)
     {
      const int m1_count=ArraySize(m_m1_history);
      if(m1_count==0)
         return;
      const datetime current_m1_time=m_m1_history[m1_count-1].open_time;
      RevisedM5Setup setup;
      if(!m_revised_detector.Update(
            m_m5_history,current_m1_time,side,setup))
        {
         string termination_reason="";
         if(!m_revised_detector.PopTermination(
               side,setup,termination_reason))
            return;
         CRevisedSnapshot terminal_snapshot;
         BuildRevisedSnapshot(side,setup,terminal_snapshot);
         m_revised_engine.TerminalDecision(
            terminal_snapshot,termination_reason,m_last_revised_decision);
         m_has_revised_decision=true;
         return;
        }

      CRevisedSnapshot snapshot;
      BuildRevisedSnapshot(side,setup,snapshot);
      string error="";
      if(!m_revised_engine.Evaluate(snapshot,m_last_revised_decision,error))
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),error);
         return;
        }
      m_has_revised_decision=true;
      if(m_last_revised_decision.state==REVISED_STATE_ENTRY_READY)
        {
         SetEvent(
            ENGINE_EVENT_ENTRY_READY,m_last_revised_decision.time,
            m_last_revised_decision.reason);
         m_revised_detector.Consume(side,setup.trigger_time);
        }
      else if(m_last_revised_decision.state==REVISED_STATE_CANCELLED)
         m_revised_detector.Consume(side,setup.trigger_time);
     }

   void DispatchClosedBar(const EngineBar &bar)
     {
      m_state.bars_processed++;
      SetEvent(ENGINE_EVENT_BAR_CLOSED,bar.close_time,
               EnumToString(bar.timeframe));
      if(bar.timeframe==PERIOD_D1)
         AppendBounded(m_d1_history,bar,64);
      else if(bar.timeframe==PERIOD_H1)
         AppendBounded(m_h1_history,bar,256);
      else if(bar.timeframe==PERIOD_M15)
         AppendBounded(m_m15_history,bar,512);
      else if(bar.timeframe==PERIOD_M5)
         AppendBounded(m_m5_history,bar,512);
      else if(bar.timeframe==PERIOD_M1)
        {
         AppendBounded(m_m1_history,bar,512);
         EvaluateRevisedSide(ENGINE_SIDE_BUY);
         if(m_data_healthy)
            EvaluateRevisedSide(ENGINE_SIDE_SELL);
        }
     }

   void CheckActiveSetupTick(const EngineTick &tick)
     {
      // Bounded live-tick hook. No strategy or order authority exists in G11.
      if(tick.time_msc<=0)
         m_data_healthy=false;
     }

public:
   CGoldEngineRuntime(void)
     {
      m_initialized=false;
      m_data_healthy=false;
      m_state.phase=ENGINE_PHASE_IDLE;
      m_state.warmed=false;
      m_state.active_setup=false;
      m_state.setup_created_at=0;
      m_state.bars_processed=0;
      m_state.setup_id="";
      m_last_event.type=ENGINE_EVENT_NONE;
      m_has_revised_decision=false;
     }

   int Initialize(const long expected_login,const string expected_server)
     {
      LoadBuildProfile(m_profile);
      string reason="";
      if(!ValidateBuildProfile(m_profile,expected_login,expected_server,reason))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=",reason);
         return INIT_FAILED;
        }
      if(!Warmup())
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=WARMUP_INCOMPLETE");
         return INIT_FAILED;
        }
      if(!m_scheduler.Initialize(m_profile.symbol))
        {
         Print("GOLD_ENGINE_INIT_REJECT profile=",m_profile.profile_id,
               " reason=SCHEDULER_INIT_FAILED");
         return INIT_FAILED;
        }

      m_data_healthy=true;
      m_initialized=true;
      m_revised_engine.Initialize(m_profile.symbol);
      m_revised_detector.SetMaximumAgeBars(60);
      const int m5_count=ArraySize(m_m5_history);
      if(m5_count>0)
         m_revised_detector.SeedWarmup(
            m_m5_history[m5_count-1].open_time);
      SetEvent(ENGINE_EVENT_RUNTIME_READY,TimeCurrent(),"WARMUP_COMPLETE");
      Print("GOLD_ENGINE_READY profile=",m_profile.profile_id,
            " fingerprint=",m_profile.profile_fingerprint,
            " order_authority=DISABLED");
      return INIT_SUCCEEDED;
     }

   void OnTick(void)
     {
      if(!m_initialized || !m_data_healthy)
         return;

      MqlTick raw_tick;
      if(!SymbolInfoTick(m_profile.symbol,raw_tick))
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),"TICK_UNAVAILABLE");
         return;
        }
      EngineTick tick;
      tick.time_msc=raw_tick.time_msc;
      tick.bid=raw_tick.bid;
      tick.ask=raw_tick.ask;
      tick.last=raw_tick.last;

      EngineBar closed_bars[];
      int bar_count=0;
      bool gap_detected=false;
      if(!m_scheduler.Poll(closed_bars,bar_count,gap_detected))
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_ERROR,TimeCurrent(),"SCHEDULER_POLL_FAILED");
         return;
        }
      if(gap_detected)
        {
         m_data_healthy=false;
         SetEvent(ENGINE_EVENT_DATA_GAP,TimeCurrent(),"CLOSED_BAR_GAP");
         Print("GOLD_ENGINE_FAIL_CLOSED profile=",m_profile.profile_id,
               " reason=CLOSED_BAR_GAP");
         return;
        }

      for(int index=0;index<bar_count;index++)
         DispatchClosedBar(closed_bars[index]);

      if(m_state.active_setup)
         CheckActiveSetupTick(tick);
     }

   void Deinitialize(const int reason)
     {
      m_initialized=false;
      m_data_healthy=false;
      Print("GOLD_ENGINE_STOP profile=",m_profile.profile_id,
            " reason=",reason);
     }

   long BarsProcessed(void) const
     {
      return m_state.bars_processed;
     }

   bool IsDataHealthy(void) const
     {
      return m_data_healthy;
     }

   bool HasRevisedDecision(void) const
     {
      return m_has_revised_decision;
     }

   RevisedDecision LastRevisedDecision(void) const
     {
      return m_last_revised_decision;
     }
  };

#endif
